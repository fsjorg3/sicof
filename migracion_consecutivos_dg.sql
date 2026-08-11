-- SICOF: separa la secuencia DG por tipo documental.
-- Ejecutar una sola vez en PostgreSQL, después de respaldar la base.
-- Conserva usuarios y clasificaciones; elimina únicamente documentos y folios.

BEGIN;

DELETE FROM documentos;
DELETE FROM consecutivos;
DELETE FROM consecutivos_dg;

ALTER TABLE consecutivos_dg
    ADD COLUMN tipo VARCHAR(50) NOT NULL,
    ADD COLUMN anio INTEGER NOT NULL;

ALTER TABLE consecutivos_dg
    ADD CONSTRAINT uq_consecutivos_dg_tipo_anio_numero
    UNIQUE (tipo, anio, numero);

CREATE INDEX IF NOT EXISTS ix_documentos_folio_tipo_anio_consecutivo
    ON documentos (tipo, anio, consecutivo);

CREATE INDEX IF NOT EXISTS ix_documentos_folio_gerencia_tipo_anio_consecutivo
    ON documentos (gerencia_solicita, tipo, anio, consecutivo);

COMMIT;
