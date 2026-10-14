-- Se ejecuta una sola vez al crear el volumen del MariaDB de desarrollo/pruebas.
-- SOLO para desarrollo: la clave es pública.
CREATE DATABASE IF NOT EXISTS licenses          CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS licenses_test     CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- charset por defecto distinto a propósito: así la prueba de migraciones demuestra que las
-- tablas fijan InnoDB/utf8mb4 y no heredan el valor del servidor.
CREATE DATABASE IF NOT EXISTS licenses_mig_test CHARACTER SET latin1;
CREATE USER IF NOT EXISTS 'lic'@'%' IDENTIFIED BY 'lic_dev_pass';
GRANT ALL PRIVILEGES ON licenses.*          TO 'lic'@'%';
GRANT ALL PRIVILEGES ON licenses_test.*     TO 'lic'@'%';
GRANT ALL PRIVILEGES ON licenses_mig_test.* TO 'lic'@'%';
