
CREATE TABLE datasets (
    dataset_id UUID PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    file_size BIGINT NOT NULL,
    storage_path TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'uploaded',
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
