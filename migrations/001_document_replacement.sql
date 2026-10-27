-- MySQL 8.0+/InnoDB. Apply once, manually, to staging first.
-- Never executed at service startup. No existing document/status/history is rewritten.
-- DDL commits implicitly: take a backup and schedule a maintenance window.
DELIMITER $$
CREATE PROCEDURE jobstep_replacement_preflight()
SQL SECURITY INVOKER
BEGIN
    IF (SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name IN ('idk_kandidati', 'idk_pp_documents', 'idk_documents', 'idk_pp_documents_status_logs')
          AND engine = 'InnoDB') <> 4 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Replacement requires all four writable/locked tables to use InnoDB';
    END IF;
    IF @@session.sql_mode NOT LIKE '%STRICT_TRANS_TABLES%'
       AND @@session.sql_mode NOT LIKE '%STRICT_ALL_TABLES%' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Create the intake routine under strict SQL mode';
    END IF;
END$$
DELIMITER ;
CALL jobstep_replacement_preflight();
DROP PROCEDURE jobstep_replacement_preflight;

ALTER TABLE idk_pp_documents
    ADD COLUMN doc_replaces_id BIGINT NULL,
    ADD COLUMN doc_intake_type_id BIGINT NULL,
    ADD COLUMN doc_intake_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    ADD UNIQUE KEY jobstep_one_replacement (doc_replaces_id),
    ADD UNIQUE KEY jobstep_one_intake (doc_intake_key),
    ADD KEY jobstep_current_document (doc_candidate_id, doc_nalog_id, doc_intake_type_id, doc_id);

DELIMITER $$
-- Protect the historical predecessor, including writes from the existing CRM.
-- A current/locking read sees a successor committed while an UPDATE waited.
CREATE TRIGGER jobstep_preserve_replaced_document
BEFORE UPDATE ON idk_pp_documents
FOR EACH ROW
BEGIN
    DECLARE v_successor BIGINT DEFAULT NULL;
    IF NOT (NEW.doc_status <=> OLD.doc_status)
       OR NOT (NEW.doc_file_name <=> OLD.doc_file_name)
       OR NOT (NEW.doc_candidate_id <=> OLD.doc_candidate_id)
       OR NOT (NEW.doc_nalog_id <=> OLD.doc_nalog_id)
       OR NOT (NEW.doc_nrd_id <=> OLD.doc_nrd_id) THEN
        SELECT doc_id INTO v_successor FROM idk_pp_documents
            WHERE doc_replaces_id = OLD.doc_id LIMIT 1 FOR SHARE;
        IF v_successor IS NOT NULL THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Ersetztes Dokument bleibt unveraendert; aktuellen Nachfolger bearbeiten';
        END IF;
    END IF;
END$$

CREATE PROCEDURE jobstep_document_intake_v1(
    IN p_candidate BIGINT,
    IN p_order BIGINT,
    IN p_type BIGINT,
    IN p_url VARCHAR(500),
    IN p_requirement BIGINT,
    IN p_replaces BIGINT,
    IN p_comment VARCHAR(500)
)
SQL SECURITY INVOKER
intake: BEGIN
    DECLARE v_candidate BIGINT DEFAULT NULL;
    DECLARE v_predecessor BIGINT DEFAULT NULL;
    DECLARE v_doc BIGINT DEFAULT NULL;
    DECLARE v_requirement BIGINT DEFAULT NULL;
    DECLARE v_type_name VARCHAR(255);
    DECLARE v_icon VARCHAR(5);
    DECLARE v_key CHAR(64);
    DECLARE v_count INT DEFAULT 0;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF p_candidate IS NULL OR p_candidate <= 0 OR p_order IS NULL OR p_order <= 0
       OR p_type IS NULL OR p_type <= 0 OR (p_replaces IS NOT NULL AND p_replaces <= 0)
       OR p_url IS NULL OR LEFT(p_url, 8) <> 'https://' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Ungueltige Intake-Parameter';
    END IF;

    START TRANSACTION;
    -- Every MCP intake for this candidate uses the same lock, including initial uploads.
    -- The lock lasts through all three writes; one HTTP CALL uses one DB connection.
    SELECT kandidat_id INTO v_candidate FROM idk_kandidati
        WHERE kandidat_id = p_candidate FOR UPDATE;
    IF v_candidate IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Kandidat existiert nicht';
    END IF;
    -- Status tools/CRM writers lock this row too. Acquire it before the first
    -- consistent read, so a status change that wins first is not read from a stale snapshot.
    IF p_replaces IS NOT NULL THEN
        SELECT doc_id INTO v_predecessor FROM idk_pp_documents
            WHERE doc_id = p_replaces AND doc_candidate_id = p_candidate AND doc_nalog_id = p_order
            FOR UPDATE;
        IF v_predecessor IS NULL THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Ersatz-Dokument passt nicht zu Kandidat und Auftrag';
        END IF;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM idk_nalozi WHERE nalog_id = p_order) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Auftrag existiert nicht';
    END IF;
    SELECT doc_type_name INTO v_type_name FROM idk_pp_document_types WHERE doc_type_id = p_type;
    IF v_type_name IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Dokumenttyp existiert nicht';
    END IF;
    IF p_requirement IS NOT NULL THEN
        SELECT nrd_id INTO v_requirement FROM idk_pp_nalog_required_documents
            WHERE nrd_id = p_requirement AND nrd_nalog_id = p_order
              AND nrd_type_id = p_type AND nrd_status = 1;
        IF v_requirement IS NULL THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Pflichtposition passt nicht zu Auftrag und Dokumenttyp';
        END IF;
    ELSE
        SELECT COUNT(*) INTO v_count FROM idk_pp_nalog_required_documents
            WHERE nrd_nalog_id = p_order AND nrd_type_id = p_type AND nrd_status = 1;
        IF v_count > 1 THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Mehrdeutige Pflichtposition: nrd_id angeben';
        END IF;
        SELECT MIN(nrd_id) INTO v_requirement FROM idk_pp_nalog_required_documents
            WHERE nrd_nalog_id = p_order AND nrd_type_id = p_type AND nrd_status = 1;
    END IF;

    SET v_key = SHA2(CONCAT(p_candidate, ':', p_order, ':', p_type, ':', COALESCE(p_replaces, 0)), 256);
    SELECT doc_id INTO v_doc FROM idk_pp_documents WHERE doc_intake_key = v_key;
    IF v_doc IS NOT NULL THEN
        -- Same operation and exact file: replay the committed result, never reset status.
        IF NOT EXISTS (SELECT 1 FROM idk_pp_documents
            WHERE doc_id = v_doc AND BINARY doc_file_name = BINARY p_url
              AND doc_nrd_id <=> v_requirement) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Intake bereits mit anderer Datei oder Pflichtposition ausgefuehrt';
        END IF;
        COMMIT;
        SELECT 1 AS intake_version, v_doc AS doc_id, p_replaces AS ersetzt_doc_id,
               doc_status, v_type_name AS unterlagentyp, 1 AS wiederverwendet
               FROM idk_pp_documents WHERE doc_id = v_doc;
        LEAVE intake;
    END IF;

    -- Do not infer the type of legacy unlinked rows; fail closed instead of duplicating.
    IF EXISTS (SELECT 1 FROM idk_pp_documents d
        LEFT JOIN idk_pp_nalog_required_documents r ON r.nrd_id = d.doc_nrd_id
        WHERE d.doc_candidate_id = p_candidate AND d.doc_nalog_id = p_order
          AND COALESCE(d.doc_intake_type_id, r.nrd_type_id) IS NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Altbestand ohne Dokumenttyp: manuell klaeren';
    END IF;

    -- No LIMIT: older blocking documents cannot disappear behind the first tool page.
    IF EXISTS (SELECT 1 FROM idk_pp_documents d
        LEFT JOIN idk_pp_nalog_required_documents r ON r.nrd_id = d.doc_nrd_id
        WHERE d.doc_candidate_id = p_candidate AND d.doc_nalog_id = p_order
          AND COALESCE(d.doc_intake_type_id, r.nrd_type_id) = p_type
          AND NOT EXISTS (SELECT 1 FROM idk_pp_documents child WHERE child.doc_replaces_id = d.doc_id)
          AND (d.doc_status IS NULL OR d.doc_status NOT IN (21, 24))) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Vorhandenes aktuelles Dokument blockiert Intake';
    END IF;

    SELECT COUNT(*) INTO v_count FROM idk_pp_documents d
        LEFT JOIN idk_pp_nalog_required_documents r ON r.nrd_id = d.doc_nrd_id
        WHERE d.doc_candidate_id = p_candidate AND d.doc_nalog_id = p_order
          AND COALESCE(d.doc_intake_type_id, r.nrd_type_id) = p_type
          AND NOT EXISTS (SELECT 1 FROM idk_pp_documents child WHERE child.doc_replaces_id = d.doc_id);
    IF v_count > 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Mehrere aktuelle Alt-Dokumente: manuell klaeren';
    END IF;
    IF p_replaces IS NULL AND v_count > 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Ersatzaufnahme erfordert ersetzt_doc_id';
    END IF;
    IF p_replaces IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM idk_pp_documents d
        LEFT JOIN idk_pp_nalog_required_documents r ON r.nrd_id = d.doc_nrd_id
        WHERE d.doc_id = p_replaces AND d.doc_candidate_id = p_candidate AND d.doc_nalog_id = p_order
          AND COALESCE(d.doc_intake_type_id, r.nrd_type_id) = p_type AND d.doc_status IN (21, 24)
          AND d.doc_nrd_id <=> v_requirement
          AND NOT EXISTS (SELECT 1 FROM idk_pp_documents child WHERE child.doc_replaces_id = d.doc_id)
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Ersatz-Dokument passt nicht oder wurde bereits ersetzt';
    END IF;

    INSERT INTO idk_pp_documents
        (doc_file_name, doc_candidate_id, doc_nalog_id, doc_nrd_id, doc_status,
         doc_replaces_id, doc_intake_type_id, doc_intake_key)
    VALUES (p_url, p_candidate, p_order, v_requirement, 3, p_replaces, p_type, v_key);
    SET v_doc = LAST_INSERT_ID();
    SET v_icon = IF(SUBSTRING_INDEX(SUBSTRING_INDEX(p_url, '?', 1), '/', -1) LIKE '%.%',
        LEFT(LOWER(SUBSTRING_INDEX(SUBSTRING_INDEX(p_url, '?', 1), '.', -1)), 5), 'bin');
    INSERT INTO idk_documents
        (document_name, document_desc, document_file, document_icon, document_datetime,
         document_group, document_dataid, document_employeeid)
    VALUES (v_type_name, COALESCE(p_comment, ''), p_url, v_icon, NOW(), 2, p_candidate, 0);
    INSERT INTO idk_pp_documents_status_logs
        (dsl_doc_id, dsl_doc_status, dsl_date, dsl_user_id, dsl_days_count, dsl_comment)
    VALUES (v_doc, 3, NOW(), 0, 0,
        LEFT(CONCAT('Agent: Unterlage angelegt (Hochgeladen). Datei: ', p_url,
            IF(p_replaces IS NULL, '', CONCAT(' | Ersatz fuer Dokument ', p_replaces)),
            IF(COALESCE(p_comment, '') = '', '', CONCAT(' | ', p_comment))), 900));
    COMMIT;
    SELECT 1 AS intake_version, v_doc AS doc_id, p_replaces AS ersetzt_doc_id,
           3 AS doc_status, v_type_name AS unterlagentyp, 0 AS wiederverwendet;
END$$
DELIMITER ;
