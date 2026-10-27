CREATE TABLE idk_kandidati (
    kandidat_id BIGINT PRIMARY KEY, kandidat_ime VARCHAR(80), kandidat_prezime VARCHAR(80), kandidat_nalog_id BIGINT
) ENGINE=InnoDB;
CREATE TABLE idk_nalozi (nalog_id BIGINT PRIMARY KEY) ENGINE=InnoDB;
CREATE TABLE idk_pp_document_types (
    doc_type_id BIGINT PRIMARY KEY, doc_type_name VARCHAR(255), doc_type_name_de VARCHAR(255)
) ENGINE=InnoDB;
CREATE TABLE idk_pp_nalog_required_documents (
    nrd_id BIGINT PRIMARY KEY, nrd_type_id BIGINT, nrd_nalog_id BIGINT, nrd_status INT
) ENGINE=InnoDB;
CREATE TABLE idk_pp_documents (
    doc_id BIGINT AUTO_INCREMENT PRIMARY KEY, doc_file_name VARCHAR(500),
    doc_candidate_id BIGINT, doc_nalog_id BIGINT, doc_nrd_id BIGINT, doc_status INT,
    INDEX candidate_order (doc_candidate_id, doc_nalog_id)
) ENGINE=InnoDB;
CREATE TABLE idk_documents (
    document_id BIGINT AUTO_INCREMENT PRIMARY KEY, document_name VARCHAR(255),
    document_desc TEXT, document_file VARCHAR(500), document_icon VARCHAR(10),
    document_datetime DATETIME, document_group INT, document_dataid BIGINT, document_employeeid BIGINT
) ENGINE=InnoDB;
CREATE TABLE idk_pp_documents_status_logs (
    dsl_id BIGINT AUTO_INCREMENT PRIMARY KEY, dsl_doc_id BIGINT, dsl_doc_status INT,
    dsl_date DATETIME, dsl_user_id BIGINT, dsl_days_count INT, dsl_comment TEXT
) ENGINE=InnoDB;
INSERT INTO idk_kandidati VALUES (100,'Synthetic','Candidate',30),(101,'Other','Candidate',31);
INSERT INTO idk_nalozi VALUES (30),(31);
INSERT INTO idk_pp_document_types VALUES (20,'Putovnica','Pass'),(21,'Diploma','Zeugnis');
INSERT INTO idk_pp_nalog_required_documents VALUES (10,20,30,1),(11,21,30,1),(12,20,31,1);
