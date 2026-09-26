"""Seed demo SQLite databases for NL-to-SQL Assistant:
- data/demo_hospital.db
- data/demo_ecommerce.db
"""

import sqlite3
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HOSPITAL_DB = DATA_DIR / "demo_hospital.db"
ECOMMERCE_DB = DATA_DIR / "demo_ecommerce.db"


def seed_hospital_db():
    conn = sqlite3.connect(HOSPITAL_DB)
    cursor = conn.cursor()

    # Drop old tables if re-running
    cursor.execute("DROP TABLE IF EXISTS appointments")
    cursor.execute("DROP TABLE IF EXISTS patients")
    cursor.execute("DROP TABLE IF EXISTS doctors")

    # Create tables
    cursor.execute(
        """
        CREATE TABLE patients (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            diagnosis TEXT,
            admission_date TEXT
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE doctors (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            specialty TEXT NOT NULL
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE appointments (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            doctor_id INTEGER NOT NULL,
            appointment_date TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (patient_id) REFERENCES patients (id),
            FOREIGN KEY (doctor_id) REFERENCES doctors (id)
        );
        """
    )

    # 13 Patients
    patients = [
        (1, "Alice Jenkins", 45, "Female", "Hypertension", "2024-01-15"),
        (2, "Karthik Raj", 32, "Male", "Fever", "2024-01-17"),
        (3, "Harini Krishnan", 27, "Female", "Allergy", "2024-01-19"),
        (4, "Robert Martinez", 62, "Male", "Type 2 Diabetes", "2024-01-18"),
        (5, "Clara Oswald", 29, "Female", "Asthma", "2024-02-01"),
        (6, "David Kim", 53, "Male", "Coronary Artery Disease", "2024-02-10"),
        (7, "Elena Rostova", 34, "Female", "Migraine", "2024-02-14"),
        (8, "Frank Gallagher", 71, "Male", "Pneumonia", "2024-02-20"),
        (9, "Grace Hopper", 85, "Female", "Arrhythmia", "2024-03-01"),
        (10, "Henry Cavill", 40, "Male", "Lumbar Disc Herniation", "2024-03-05"),
        (11, "Irene Adler", 38, "Female", "Hyperthyroidism", "2024-03-12"),
        (12, "James Wilson", 50, "Male", "Chronic Kidney Disease", "2024-03-15"),
        (13, "Pavai", 28, "Female", "Checkup", "2024-03-20"),
    ]
    cursor.executemany(
        "INSERT INTO patients (id, name, age, gender, diagnosis, admission_date) VALUES (?, ?, ?, ?, ?, ?);",
        patients,
    )

    # 8 Doctors
    doctors = [
        (1, "Dr. Gregory House", "Nephrology"),
        (2, "Dr. Lisa Cuddy", "Endocrinology"),
        (3, "Dr. James Wilson", "Oncology"),
        (4, "Dr. Allison Cameron", "Immunology"),
        (5, "Dr. Robert Chase", "Cardiology"),
        (6, "Dr. Eric Foreman", "Neurology"),
        (7, "Dr. Chris Turk", "Orthopedics"),
        (8, "Dr. John Dorian", "Internal Medicine"),
    ]
    cursor.executemany(
        "INSERT INTO doctors (id, name, specialty) VALUES (?, ?, ?);",
        doctors,
    )

    # 10 Appointments
    appointments = [
        (1, 1, 5, "2024-01-20", "Completed"),
        (2, 2, 2, "2024-01-25", "Completed"),
        (3, 3, 8, "2024-02-05", "Completed"),
        (4, 4, 5, "2024-02-15", "Completed"),
        (5, 5, 6, "2024-02-22", "Completed"),
        (6, 6, 8, "2024-02-28", "Cancelled"),
        (7, 7, 5, "2024-03-08", "Completed"),
        (8, 8, 7, "2024-03-15", "Scheduled"),
        (9, 9, 2, "2024-03-20", "Scheduled"),
        (10, 10, 1, "2024-03-22", "Scheduled"),
    ]
    cursor.executemany(
        "INSERT INTO appointments (id, patient_id, doctor_id, appointment_date, status) VALUES (?, ?, ?, ?, ?);",
        appointments,
    )

    conn.commit()

    # Query counts
    cursor.execute("SELECT COUNT(*) FROM patients")
    p_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM doctors")
    d_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM appointments")
    a_count = cursor.fetchone()[0]

    conn.close()

    print(f"[Hospital DB] Seeded successfully -> {HOSPITAL_DB}")
    print(f"  - patients: {p_count} rows")
    print(f"  - doctors: {d_count} rows")
    print(f"  - appointments: {a_count} rows")


def seed_ecommerce_db():
    conn = sqlite3.connect(ECOMMERCE_DB)
    cursor = conn.cursor()

    # Drop old tables if re-running
    cursor.execute("DROP TABLE IF EXISTS orders")
    cursor.execute("DROP TABLE IF EXISTS products")
    cursor.execute("DROP TABLE IF EXISTS customers")

    # Create tables
    cursor.execute(
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            city TEXT,
            signup_date TEXT
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            price REAL NOT NULL,
            stock INTEGER NOT NULL
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            order_date TEXT NOT NULL,
            total_amount REAL NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        );
        """
    )

    # 12 Customers
    customers = [
        (1, "Sophia Chen", "sophia.chen@example.com", "San Francisco", "2023-05-12"),
        (2, "Liam Johnson", "liam.j@example.com", "Seattle", "2023-06-01"),
        (3, "Emma Watson", "emma.w@example.com", "New York", "2023-07-15"),
        (4, "Noah Miller", "noah.m@example.com", "Austin", "2023-08-20"),
        (5, "Olivia Garcia", "olivia.g@example.com", "Chicago", "2023-09-04"),
        (6, "Lucas Brown", "lucas.b@example.com", "Denver", "2023-10-10"),
        (7, "Ava Davis", "ava.d@example.com", "Boston", "2023-11-02"),
        (8, "Ethan Taylor", "ethan.t@example.com", "Los Angeles", "2023-11-25"),
        (9, "Mia Wilson", "mia.w@example.com", "Miami", "2023-12-14"),
        (10, "Alexander White", "alex.w@example.com", "Portland", "2024-01-08"),
        (11, "Isabella Martinez", "isabella.m@example.com", "Phoenix", "2024-01-22"),
        (12, "Mason Lee", "mason.lee@example.com", "San Jose", "2024-02-11"),
    ]
    cursor.executemany(
        "INSERT INTO customers (id, name, email, city, signup_date) VALUES (?, ?, ?, ?, ?);",
        customers,
    )

    # 12 Products
    products = [
        (1, "Noise-Cancelling Headphones", "Electronics", 199.99, 45),
        (2, "Mechanical Keyboard", "Electronics", 89.99, 80),
        (3, "Ultra-Wide Gaming Monitor", "Electronics", 349.50, 25),
        (4, "Ergonomic Office Chair", "Furniture", 249.00, 15),
        (5, "Standing Desk Converter", "Furniture", 179.99, 20),
        (6, "Stainless Steel Water Bottle", "Home & Kitchen", 24.99, 150),
        (7, "Espresso Machine", "Home & Kitchen", 299.00, 18),
        (8, "Organic Cotton T-Shirt", "Apparel", 29.50, 120),
        (9, "Waterproof Running Jacket", "Apparel", 89.00, 40),
        (10, "Bluetooth Portable Speaker", "Electronics", 59.99, 95),
        (11, "Memory Foam Pillow", "Home & Kitchen", 39.99, 60),
        (12, "Trail Running Shoes", "Apparel", 119.95, 35),
    ]
    cursor.executemany(
        "INSERT INTO products (id, name, category, price, stock) VALUES (?, ?, ?, ?, ?);",
        products,
    )

    # 12 Orders
    orders = [
        (1, 1, 1, 1, "2024-02-01", 199.99),
        (2, 2, 2, 2, "2024-02-03", 179.98),
        (3, 3, 4, 1, "2024-02-05", 249.00),
        (4, 4, 3, 1, "2024-02-08", 349.50),
        (5, 5, 6, 3, "2024-02-10", 74.97),
        (6, 6, 7, 1, "2024-02-12", 299.00),
        (7, 7, 8, 2, "2024-02-14", 59.00),
        (8, 8, 10, 1, "2024-02-18", 59.99),
        (9, 9, 9, 1, "2024-02-20", 89.00),
        (10, 10, 12, 1, "2024-02-22", 119.95),
        (11, 11, 11, 2, "2024-02-25", 79.98),
        (12, 12, 5, 1, "2024-02-28", 179.99),
    ]
    cursor.executemany(
        "INSERT INTO orders (id, customer_id, product_id, quantity, order_date, total_amount) VALUES (?, ?, ?, ?, ?, ?);",
        orders,
    )

    conn.commit()

    # Query counts
    cursor.execute("SELECT COUNT(*) FROM customers")
    c_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM products")
    p_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM orders")
    o_count = cursor.fetchone()[0]

    conn.close()

    print(f"[Ecommerce DB] Seeded successfully -> {ECOMMERCE_DB}")
    print(f"  - customers: {c_count} rows")
    print(f"  - products: {p_count} rows")
    print(f"  - orders: {o_count} rows")


if __name__ == "__main__":
    print("Seeding demo SQLite databases...")
    seed_hospital_db()
    seed_ecommerce_db()
    print("Database seeding completed successfully!")
