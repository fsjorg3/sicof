import io
import os
import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd


os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("FLASK_DEBUG", "1")
os.environ.setdefault("SICOF_ADMIN_PASSWORD", "test-password")

from sicof import create_app, db
from sicof.app import _tipo_documento_importado
from sicof.constantes import TIPOS_DOCUMENTO
from sicof.models import (
    Clasificacion,
    Consecutivo,
    ConsecutivoDG,
    Documento,
    Usuario,
    establecer_tope_manual,
    generar_numero_documento,
    registrar_folio_importado,
)


class ConsecutivosTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.anio = datetime.now().year

    def setUp(self):
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()
        self.contexto.pop()

    def agregar_documento(self, tipo, numero, gerencia="GAL", estatus="normal"):
        db.session.add(
            Documento(
                tipo=tipo,
                numero=f"{gerencia}/{numero:04d}/{self.anio}",
                consecutivo=numero,
                anio=self.anio,
                asunto="Documento de prueba",
                fecha_recepcion=f"{self.anio}-01-01",
                gerencia_solicita=gerencia,
                estatus=estatus,
            )
        )

    def test_usa_maximo_documento_si_el_contador_esta_atrasado(self):
        self.agregar_documento("oficio_int", 25)
        db.session.add(
            Consecutivo(
                gerencia="GLOBAL",
                tipo="oficio_int",
                anio=self.anio,
                numero=10,
            )
        )
        db.session.commit()

        numero, consecutivo, anio = generar_numero_documento("GAL", "oficio_int")

        self.assertEqual(numero, f"GAL/0026/{self.anio}")
        self.assertEqual(consecutivo, 26)
        self.assertEqual(anio, self.anio)

    def test_tope_manual_mayor_al_maximo_se_respeta(self):
        self.agregar_documento("oficio_int", 25)
        db.session.commit()

        establecer_tope_manual("oficio_int", 40)
        db.session.commit()

        _, consecutivo, _ = generar_numero_documento("GAL", "oficio_int")

        self.assertEqual(consecutivo, 41)

    def test_cancelados_y_reservados_forman_parte_del_maximo(self):
        self.agregar_documento("oficio_int", 10, estatus="reservado")
        self.agregar_documento("oficio_int", 12, estatus="cancelado")
        db.session.commit()

        _, consecutivo, _ = generar_numero_documento("GAL", "oficio_int")

        self.assertEqual(consecutivo, 13)

    def test_tipos_dg_mantienen_secuencias_independientes(self):
        self.agregar_documento("oficio_dg", 10, gerencia="DG")
        self.agregar_documento("oficio_circular_dg", 10, gerencia="DG")
        db.session.commit()

        _, oficio, _ = generar_numero_documento("DG", "oficio_dg")
        db.session.commit()
        _, circular, _ = generar_numero_documento("DG", "oficio_circular_dg")
        db.session.commit()
        _, siguiente_oficio, _ = generar_numero_documento("DG", "oficio_dg")

        self.assertEqual(oficio, 11)
        self.assertEqual(circular, 11)
        self.assertEqual(siguiente_oficio, 12)

        filas = ConsecutivoDG.query.order_by(ConsecutivoDG.tipo).all()
        self.assertEqual(
            [(fila.tipo, fila.anio, fila.numero) for fila in filas],
            [
                ("oficio_circular_dg", self.anio, 11),
                ("oficio_dg", self.anio, 11),
                ("oficio_dg", self.anio, 12),
            ],
        )

    def test_tipos_internos_conservan_secuencias_separadas(self):
        self.agregar_documento("oficio_int", 25)
        self.agregar_documento("oficio_circular_int", 40)
        db.session.commit()

        _, oficio, _ = generar_numero_documento("GAL", "oficio_int")
        _, circular, _ = generar_numero_documento("GAL", "oficio_circular_int")

        self.assertEqual(oficio, 26)
        self.assertEqual(circular, 41)

    def test_importacion_actualiza_un_tope_global_por_tipo(self):
        registrar_folio_importado(
            "GAL", "oficio_int", self.anio, 280, "registrado", None, "Importado"
        )
        registrar_folio_importado(
            "GAL", "oficio_int", self.anio, 281, "registrado", None, "Importado"
        )
        db.session.commit()

        contadores = Consecutivo.query.filter_by(
            gerencia="GLOBAL", tipo="oficio_int", anio=self.anio
        ).all()
        self.assertEqual(len(contadores), 1)
        self.assertEqual(contadores[0].numero, 281)

        _, consecutivo, _ = generar_numero_documento("GAL", "oficio_int")
        self.assertEqual(consecutivo, 282)

    def test_importacion_dg_no_altera_otro_tipo(self):
        registrar_folio_importado(
            "DG", "oficio_dg", self.anio, 280, "registrado", None, "Importado"
        )
        db.session.commit()

        _, consecutivo, _ = generar_numero_documento("DG", "oficio_circular_dg")

        self.assertEqual(consecutivo, 1)
        self.assertEqual(
            ConsecutivoDG.query.filter_by(tipo="oficio_dg").one().numero,
            280,
        )

    def test_documento_post_no_produce_name_error(self):
        usuario = Usuario(
            nombre="prueba",
            password_hash="no-se-usa",
            rol="superadmin",
            gerencia="GAL",
            activo=True,
        )
        clasificacion = Clasificacion(codigo="00.0", nombre="Prueba")
        db.session.add_all([usuario, clasificacion])
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion["usuario_id"] = usuario.id
            sesion["usuario_rol"] = "superadmin"
            sesion["usuario_gerencia"] = "GAL"

        respuesta = cliente.post(
            "/documentos/nuevo",
            data={
                "tipo": "oficio_int",
                "gerencia_solicita": "GAL",
                "clasificacion_id": str(clasificacion.id),
                "asunto": "Alta de prueba",
                "fecha_recepcion": f"{self.anio}-01-01",
                "solicitante": "Persona de prueba",
                "consecutivo_expediente": "1",
                "anio_expediente": str(self.anio),
                "observaciones": "",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Documento.query.one().consecutivo, 1)

    def test_importacion_sin_folio_usa_generador_central(self):
        usuario = Usuario(
            nombre="importador",
            password_hash="no-se-usa",
            rol="superadmin",
            gerencia="DG",
            activo=True,
        )
        clasificacion = Clasificacion(codigo="00.0", nombre="Prueba")
        db.session.add_all([usuario, clasificacion])
        db.session.commit()

        datos = pd.DataFrame([{
            "FECHA": f"01/01/{self.anio}",
            "CLAVE": "GAL",
            "NUMERO": "",
            "A QUIEN SE DIRIGE": "",
            "CARGO": "",
            "GERENCIA": "GAL",
            "REPONSABLE": "Persona importada",
            "ASUNTO": "Importación sin folio",
            "ESTATUS": "REGISTRADO",
            "DOCUMENTO GENERADO": "",
        }])

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion["usuario_id"] = usuario.id
            sesion["usuario_rol"] = "superadmin"
            sesion["usuario_gerencia"] = "DG"

        with patch("sicof.app.pd.read_excel", return_value=datos):
            respuesta = cliente.post(
                "/importar_dg_2026",
                data={"archivo": (io.BytesIO(b"datos"), "datos.xlsx")},
                content_type="multipart/form-data",
            )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Documento.query.one().consecutivo, 1)
        self.assertEqual(
            Consecutivo.query.filter_by(
                gerencia="GLOBAL", tipo="oficio_int", anio=self.anio
            ).one().numero,
            1,
        )

    def test_clasificacion_importada_distingue_oficio_circular(self):
        self.assertEqual(
            _tipo_documento_importado("OFICIO-CIRCULAR DG", True),
            "oficio_circular_dg",
        )
        self.assertEqual(
            _tipo_documento_importado("MEMORÁNDUM-CIRCULAR", False),
            "memorandum_circular_int",
        )

    def test_configuracion_aplica_el_tope_manual_del_formulario(self):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion["usuario_id"] = 1
            sesion["usuario_rol"] = "superadmin"

        respuesta = cliente.post(
            "/configuracion",
            data={"nuevo_consecutivo_oficio_int": "40"},
        )

        self.assertEqual(respuesta.status_code, 302)
        _, consecutivo, _ = generar_numero_documento("GAL", "oficio_int")
        self.assertEqual(consecutivo, 41)

    def test_configuracion_aplica_tope_manual_independiente_para_dg(self):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion["usuario_id"] = 1
            sesion["usuario_rol"] = "superadmin"

        respuesta = cliente.post(
            "/configuracion",
            data={"nuevo_consecutivo_oficio_circular_dg": "40"},
        )

        self.assertEqual(respuesta.status_code, 302)
        _, consecutivo, _ = generar_numero_documento("DG", "oficio_circular_dg")
        self.assertEqual(consecutivo, 41)

    def test_edicion_dg_actualiza_solo_campos_del_backend(self):
        cons = ConsecutivoDG(
            tipo="oficio_dg",
            anio=self.anio,
            numero=1,
            estatus="registrado",
            fecha=None,
            asunto="Inicial",
        )
        db.session.add(cons)
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion["usuario_id"] = 1
            sesion["usuario_rol"] = "superadmin"

        pagina = cliente.get(f"/editar_consecutivo_dg/{cons.id}")
        self.assertEqual(pagina.status_code, 200)

        respuesta = cliente.post(
            f"/editar_consecutivo_dg/{cons.id}",
            data={
                "estatus": "cancelado",
                "fecha": f"{self.anio}-02-03",
                "asunto": "Actualizado",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(cons)
        self.assertEqual(cons.estatus, "cancelado")
        self.assertEqual(cons.asunto, "Actualizado")
        self.assertEqual(cons.fecha.isoformat(), f"{self.anio}-02-03")

    def test_tipos_visibles_conservan_valores_internos(self):
        self.assertEqual(
            set(TIPOS_DOCUMENTO),
            {
                "oficio_dg",
                "oficio_circular_dg",
                "memorandum_circular_dg",
                "memorandum_dg",
                "acuerdo_dg",
                "oficio_int",
                "oficio_circular_int",
                "memorandum_circular_int",
                "memorandum_int",
                "acuerdo_int",
            },
        )


if __name__ == "__main__":
    unittest.main()
