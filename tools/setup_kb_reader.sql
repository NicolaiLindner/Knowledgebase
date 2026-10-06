/* ============================================================================
   setup_kb_reader.sql — einmalig je Datenbank auszufuehren (Modul Datenbank).

   Zweck: Legt in der aktuellen Datenbank einen Benutzer 'kb_reader' an, der
   ausschliesslich lesen darf. tools/sql.py wechselt bei jeder Abfrage per
   EXECUTE AS ... WITH NO REVERT in diesen Benutzer. Die Sitzung hat danach
   keine Schreibrechte mehr, auch wenn der aufrufende Login sysadmin ist.

   'WITHOUT LOGIN' heisst: kein Serverlogin, kein Passwort, keine neue
   Anmeldemoeglichkeit von aussen. Der Benutzer ist nur als Sicherheitskontext
   innerhalb dieser einen Datenbank erreichbar.

   Ausfuehren mit einem Konto, das db_owner auf der Zieldatenbank ist:
     - SSMS: Zieldatenbank oben im Auswahlfeld waehlen, Skript ausfuehren.
     - sqlcmd:  sqlcmd -S <server> -d <datenbank> -E -i tools\setup_kb_reader.sql

   Kein USE im Skript: Es laeuft in der Datenbank, die beim Aufruf aktiv ist.
   Rueckgaengig machen:  DROP USER kb_reader;
   ============================================================================ */

/* 0. Schutz: nicht versehentlich in einer Systemdatenbank anlegen ----------- */
IF DB_NAME() IN ('master', 'model', 'msdb', 'tempdb')
BEGIN
    RAISERROR('Aktive Datenbank ist eine Systemdatenbank - Zieldatenbank waehlen (SSMS) oder -d angeben (sqlcmd).', 16, 1);
    SET NOEXEC ON;
END
GO

/* 1. Benutzer anlegen (idempotent) ---------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'kb_reader')
BEGIN
    CREATE USER kb_reader WITHOUT LOGIN;
    PRINT 'kb_reader angelegt.';
END
ELSE
    PRINT 'kb_reader existiert bereits.';
GO

/* 2. Nur Leserechte -------------------------------------------------------- */
ALTER ROLE db_datareader ADD MEMBER kb_reader;
GO

/* 3. Quelltext von Views, Prozeduren und Funktionen lesen duerfen.
      Ohne dieses Recht liefert sys.sql_modules.definition still NULL —
      db_datareader allein reicht dafuer NICHT. VIEW DEFINITION erlaubt
      ausschliesslich das Lesen von Objektdefinitionen, kein Aendern.        */
GRANT VIEW DEFINITION TO kb_reader;
GO

/* 4. Kein EXECUTE: db_datareader vergibt von sich aus kein Ausfuehrungsrecht,
      Stored Procedures bleiben damit gesperrt. Braucht die KB eine
      Skalarfunktion, hier einzeln ergaenzen:
      GRANT EXECUTE ON dbo.<funktion> TO kb_reader;                           */

/* 5. Kontrolle: was darf kb_reader wirklich? ------------------------------ */
EXECUTE AS USER = 'kb_reader';

    SELECT  Kontext        = USER_NAME()
          , Leserecht      = IS_ROLEMEMBER('db_datareader')
          , Schreibrecht   = IS_ROLEMEMBER('db_datawriter')
          , Besitzerrecht  = IS_ROLEMEMBER('db_owner')
          , SchemaAendern  = IS_ROLEMEMBER('db_ddladmin')
          , QuelltextLesen = CASE WHEN EXISTS (SELECT 1 FROM sys.sql_modules
                                               WHERE definition IS NOT NULL)
                                  THEN 1 ELSE 0 END;

REVERT;
GO

PRINT 'Fertig. Erwartet: Kontext = kb_reader, Leserecht = 1, QuelltextLesen = 1,';
PRINT '                 Schreibrecht/Besitzerrecht/SchemaAendern = 0.';
PRINT 'Naechster Schritt:  python tools/sql.py --check';
GO
SET NOEXEC OFF;
GO
