-- =============================================================================
-- 003_seed.sql  -  Synthetic demo inventory. NOT real listings.
-- Idempotent via explicit ids / natural-key conflicts.
-- =============================================================================

INSERT INTO properties (id, name, address_line, city, region, postal_code, property_type, description) VALUES
    (1, 'Maple Court Apartments', '12 Maple Street',  'Austin',     'TX', '78701', 'apartment',  'Quiet mid-rise apartments near downtown.'),
    (2, 'Riverside Lofts',        '88 River Road',    'Austin',     'TX', '78702', 'loft',       'Converted riverside lofts with rooftop access.'),
    (3, 'Cedar Park Homes',       '4 Cedar Lane',     'Round Rock', 'TX', '78664', 'townhouse',  'Low-rise townhomes with driveway parking.')
ON CONFLICT (id) DO NOTHING;

INSERT INTO amenities (id, name, category) VALUES
    (1,  'wifi',              'utility'),
    (2,  'gym',               'building'),
    (3,  'laundry',           'utility'),
    (4,  'parking',           'building'),
    (5,  'balcony',           'unit'),
    (6,  'rooftop',           'building'),
    (7,  'pet_friendly',      'policy'),
    (8,  'pool',              'building'),
    (9,  'air_conditioning',  'utility'),
    (10, 'dishwasher',        'unit')
ON CONFLICT (id) DO NOTHING;

INSERT INTO rooms
    (id, property_id, unit_label, room_type, monthly_rent, deposit, size_sqm, max_occupants, available_from, is_active, description)
VALUES
    (1,  1, '1A', 'Studio',      950.00,  950.00,  32.00, 1, CURRENT_DATE,            TRUE, 'Ground-floor studio.'),
    (2,  1, '1B', '1 Bedroom',  1250.00, 1250.00,  48.00, 2, CURRENT_DATE,            TRUE, 'One bedroom with courtyard view.'),
    (3,  1, '2A', '2 Bedroom',  1650.00, 1650.00,  68.00, 3, CURRENT_DATE,            TRUE, 'Two bedroom with balcony.'),
    (4,  1, '2B', '2 Bedroom',  1720.00, 1720.00,  70.00, 4, CURRENT_DATE + 30,       TRUE, 'Large two bedroom, available next month.'),
    (5,  2, 'R1', 'Studio',     1100.00, 1100.00,  35.00, 1, CURRENT_DATE,            TRUE, 'Loft studio with high ceilings.'),
    (6,  2, 'R2', '1 Bedroom',  1400.00, 1400.00,  52.00, 2, CURRENT_DATE,            TRUE, 'Loft one bedroom.'),
    (7,  2, 'R3', '2 Bedroom',  1850.00, 1850.00,  74.00, 3, CURRENT_DATE,            TRUE, 'Corner loft with rooftop access.'),
    (8,  2, 'R4', '3 Bedroom',  2600.00, 2600.00, 110.00, 5, CURRENT_DATE + 15,       TRUE, 'Penthouse three bedroom.'),
    (9,  3, 'C1', '1 Bedroom',  1050.00, 1050.00,  50.00, 2, CURRENT_DATE,            TRUE, 'Townhome with small yard.'),
    (10, 3, 'C2', '1 Bedroom',  1120.00, 1120.00,  55.00, 2, CURRENT_DATE,            TRUE, 'Townhome with laundry room.'),
    (11, 3, 'C3', '2 Bedroom',  1450.00, 1450.00,  72.00, 4, CURRENT_DATE,            TRUE, 'Two bedroom townhome.'),
    (12, 3, 'C4', '3 Bedroom',  1950.00, 1950.00,  96.00, 5, CURRENT_DATE,            TRUE, 'Three bedroom end unit.')
ON CONFLICT (id) DO NOTHING;

INSERT INTO room_amenities (room_id, amenity_id)
SELECT v.room_id, a.id
  FROM (VALUES
    (1,  'wifi'), (1,  'laundry'), (1,  'parking'), (1,  'air_conditioning'),
    (2,  'wifi'), (2,  'gym'),     (2,  'laundry'), (2,  'air_conditioning'),
    (3,  'wifi'), (3,  'gym'),     (3,  'parking'), (3,  'balcony'), (3,  'dishwasher'),
    (4,  'wifi'), (4,  'gym'),     (4,  'parking'), (4,  'balcony'), (4,  'pet_friendly'), (4, 'dishwasher'),
    (5,  'wifi'), (5,  'laundry'), (5,  'rooftop'), (5,  'air_conditioning'),
    (6,  'wifi'), (6,  'gym'),     (6,  'rooftop'), (6,  'parking'),
    (7,  'wifi'), (7,  'gym'),     (7,  'rooftop'), (7,  'parking'), (7,  'balcony'),
    (8,  'wifi'), (8,  'gym'),     (8,  'rooftop'), (8,  'parking'), (8,  'balcony'), (8, 'pet_friendly'),
    (9,  'wifi'), (9,  'parking'), (9,  'pet_friendly'), (9, 'air_conditioning'),
    (10, 'wifi'), (10, 'parking'), (10, 'laundry'), (10, 'air_conditioning'),
    (11, 'wifi'), (11, 'parking'), (11, 'laundry'), (11, 'pet_friendly'), (11, 'dishwasher'),
    (12, 'wifi'), (12, 'parking'), (12, 'laundry'), (12, 'pet_friendly'), (12, 'balcony')
  ) AS v(room_id, amenity_name)
  JOIN amenities a ON a.name = v.amenity_name
ON CONFLICT DO NOTHING;

INSERT INTO policies (property_id, policy_type, description) VALUES
    (1, 'pets',    'Cats and small dogs allowed with a $300 deposit.'),
    (1, 'smoking', 'No smoking anywhere on the property.'),
    (1, 'parking', 'One assigned parking space per unit.'),
    (2, 'pets',    'Pets allowed under 25 lb with a $350 deposit.'),
    (2, 'smoking', 'No smoking.'),
    (2, 'parking', 'Garage parking available for $75 per month.'),
    (3, 'pets',    'Pets allowed with a $250 deposit.'),
    (3, 'smoking', 'No smoking indoors.'),
    (3, 'parking', 'Driveway parking included.')
ON CONFLICT (property_id, policy_type) DO UPDATE SET description = EXCLUDED.description;

INSERT INTO bookings (room_id, guest_name, guest_email, check_in, check_out, status, idempotency_key) VALUES
    (2, 'Seed Guest A', 'seed-a@example.invalid', CURRENT_DATE + 5,  CURRENT_DATE + 12, 'confirmed', 'seed-booking-a'),
    (7, 'Seed Guest B', 'seed-b@example.invalid', CURRENT_DATE + 10, CURRENT_DATE + 17, 'confirmed', 'seed-booking-b'),
    (9, 'Seed Guest C', 'seed-c@example.invalid', CURRENT_DATE + 2,  CURRENT_DATE + 9,  'confirmed', 'seed-booking-c')
ON CONFLICT (idempotency_key) DO NOTHING;

INSERT INTO room_blocks (room_id, start_date, end_date, reason) VALUES
    (12, CURRENT_DATE + 3, CURRENT_DATE + 6, 'maintenance')
ON CONFLICT (room_id, start_date, end_date) DO NOTHING;

SELECT setval(pg_get_serial_sequence('properties', 'id'),
              COALESCE((SELECT MAX(id) FROM properties), 1));
SELECT setval(pg_get_serial_sequence('amenities', 'id'),
              COALESCE((SELECT MAX(id) FROM amenities), 1));
SELECT setval(pg_get_serial_sequence('rooms', 'id'),
              COALESCE((SELECT MAX(id) FROM rooms), 1));
