-- SICOF: renombra la gerencia GSPOI a GPSOI.
-- Ejecutar una sola vez después de generar y validar el respaldo.

BEGIN;

UPDATE usuarios
SET gerencia = 'GPSOI'
WHERE gerencia = 'GSPOI';

UPDATE documentos
SET
    gerencia_solicita = 'GPSOI',
    numero = regexp_replace(numero, '^GSPOI/', 'GPSOI/'),
    codigo_expediente = regexp_replace(
        codigo_expediente,
        '^SOAPAP/GSPOI/',
        'SOAPAP/GPSOI/'
    )
WHERE gerencia_solicita = 'GSPOI'
   OR numero LIKE 'GSPOI/%'
   OR codigo_expediente LIKE 'SOAPAP/GSPOI/%';

UPDATE consecutivos
SET gerencia = 'GPSOI'
WHERE gerencia = 'GSPOI';

COMMIT;
