-- Add Cloudinary public IDs for persistent company images.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS logo_public_id VARCHAR(300) DEFAULT '';
ALTER TABLE companies ADD COLUMN IF NOT EXISTS qr_public_id VARCHAR(300) DEFAULT '';
ALTER TABLE companies ADD COLUMN IF NOT EXISTS signature_public_id VARCHAR(300) DEFAULT '';
