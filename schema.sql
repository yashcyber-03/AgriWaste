-- Smart Agriculture Waste Collection and Management System
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE,
  phone         TEXT,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('farmer','worker','admin')),
  created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Waste classification + recycling suggestions (features 3 & 7)
CREATE TABLE IF NOT EXISTS categories (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  name             TEXT NOT NULL UNIQUE,
  description      TEXT,
  recycling_method TEXT NOT NULL,   -- composting | mulching | biogas | recycling
  recycling_tip    TEXT
);

-- Feature 2: what the farmer has available
CREATE TABLE IF NOT EXISTS waste_reports (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  farmer_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  quantity_kg REAL NOT NULL CHECK (quantity_kg > 0),
  notes       TEXT,
  created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Features 4, 5, 6: collection request with GPS and status lifecycle
CREATE TABLE IF NOT EXISTS collection_requests (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  report_id      INTEGER NOT NULL REFERENCES waste_reports(id) ON DELETE CASCADE,
  farmer_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  worker_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
  address        TEXT NOT NULL,
  latitude       REAL,
  longitude      REAL,
  status         TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','accepted','scheduled','collected','recycled','rejected')),
  scheduled_date TEXT,
  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Feature 9
CREATE TABLE IF NOT EXISTS notifications (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  message    TEXT NOT NULL,
  is_read    INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Feature 12
CREATE TABLE IF NOT EXISTS feedback (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id INTEGER NOT NULL REFERENCES collection_requests(id) ON DELETE CASCADE,
  farmer_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment    TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (request_id, farmer_id)
);

CREATE INDEX IF NOT EXISTS idx_req_status ON collection_requests(status);
CREATE INDEX IF NOT EXISTS idx_req_farmer ON collection_requests(farmer_id);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read);

INSERT OR IGNORE INTO categories (name, description, recycling_method, recycling_tip) VALUES
 ('Crop residue','Stalks and stubble left after harvest','mulching','Spread chopped residue on fields to retain moisture and suppress weeds. Avoid burning.'),
 ('Straw','Dry stalks of wheat, rice, barley','biogas','Shred and feed to biogas digesters, or bale for animal bedding and mushroom farming.'),
 ('Husk','Outer shells of rice, groundnut, grains','recycling','Use as biomass fuel, pressed briquettes or poultry litter.'),
 ('Leaves','Fallen and pruned leaves','composting','Layer with green waste and turn every 2 weeks for rich compost in 6-8 weeks.'),
 ('Fruit & vegetable waste','Spoiled or surplus produce','composting','Vermicompost or biogas works best. Keep it separate from plastic and twine.'),
 ('Animal manure','Cattle and poultry dung','biogas','Feed to a biogas plant; the leftover slurry is an excellent fertiliser.');
