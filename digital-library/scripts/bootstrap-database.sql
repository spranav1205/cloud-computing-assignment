-- Run once using psql as the RDS administrator, inside the VPC, connected to
-- digitallibrary. Passwords are entered through psql's hidden password prompts.
\set ON_ERROR_STOP on
CREATE ROLE library_member LOGIN;
CREATE ROLE library_reservation LOGIN;
CREATE ROLE library_lending LOGIN;
CREATE ROLE library_availability LOGIN;
CREATE ROLE library_fine LOGIN;
\password library_member
\password library_reservation
\password library_lending
\password library_availability
\password library_fine

GRANT CONNECT ON DATABASE digitallibrary TO library_member, library_reservation, library_lending, library_availability, library_fine;
GRANT USAGE ON SCHEMA public TO library_member, library_reservation, library_lending, library_availability, library_fine;
GRANT CREATE ON SCHEMA public TO library_member, library_reservation, library_lending;
-- The application owners create their existing tables during pod initialization.
-- Readers need grants before those tables are created for the first time.
ALTER DEFAULT PRIVILEGES FOR ROLE library_reservation IN SCHEMA public GRANT SELECT ON TABLES TO library_availability;
ALTER DEFAULT PRIVILEGES FOR ROLE library_lending IN SCHEMA public GRANT SELECT ON TABLES TO library_availability, library_fine;
-- If tables were already initialized, also grant access to those existing tables.
SELECT 'GRANT SELECT ON public.reservations TO library_availability' WHERE to_regclass('public.reservations') IS NOT NULL
\gexec
SELECT 'GRANT SELECT ON public.loans TO library_availability' WHERE to_regclass('public.loans') IS NOT NULL
\gexec
SELECT 'GRANT SELECT ON public.loans TO library_fine' WHERE to_regclass('public.loans') IS NOT NULL
\gexec
