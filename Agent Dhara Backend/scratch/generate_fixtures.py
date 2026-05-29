import os
import json

def generate_fixtures():
    fixtures_dir = r"c:\Users\ssakesh\Downloads\DHARA-GX\Agent Dhara Backend\tests\etl_scenarios\fixtures"
    os.makedirs(fixtures_dir, exist_ok=True)

    # 1. Happy Path
    happy_path = [
        {"id": 1, "name": "Alice", "age": 25, "joined_date": "2026-01-01"},
        {"id": 2, "name": "Bob", "age": 30, "joined_date": "2026-02-15"},
        {"id": 3, "name": "Charlie", "age": 35, "joined_date": "2026-03-10"},
    ]
    
    # 2. Dirty Dates
    dirty_dates = [
        {"id": 1, "created_at": "2026-05-16", "updated_at": "2026-05-17"},  # Saturday (weekend)
        {"id": 2, "created_at": "2026-01-01", "updated_at": "2026-01-01"},  # Jan 1 clumping
        {"id": 3, "created_at": "1800-05-05", "updated_at": "2026-05-17"},  # Ancient date
        {"id": 4, "created_at": "2028-05-05", "updated_at": "2026-05-17"},  # Future date
        {"id": 5, "created_at": "2026-05-20", "updated_at": "2026-05-10"},  # Date range violation (updated before created)
    ]
    
    # 3. Dirty Emails
    dirty_emails = [
        {"id": 1, "email": "alice@example.com"},
        {"id": 2, "email": "bob_at_example.com"},  # Malformed
        {"id": 3, "email": "charlie@"},             # Malformed
    ]
    
    # 4. Wide Table (300+ columns)
    wide_table = []
    row = {"id": 1}
    for col_idx in range(1, 310):
        row[f"col_{col_idx}"] = f"val_{col_idx}"
    wide_table.append(row)
    
    # 5. Null Primary Keys
    null_pks = [
        {"id": 1, "name": "Alice"},
        {"id": None, "name": "Bob"},  # Null PK candidate
        {"id": 3, "name": "Charlie"},
    ]
    
    # 6. FK Violations
    fk_violations = [
        {"OrderID": 1, "ParentOrderID": 1},
        {"OrderID": 2, "ParentOrderID": 1},
        {"OrderID": 3, "ParentOrderID": 99}, # 99 is orphan FK
    ]
    
    # 7. Encoding Issues
    encoding_issues = [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob\x00\x08"},  # Control chars
        {"id": 3, "name": "Chärlie"},       # Non-ASCII
    ]
    
    # 8. SCD2 Patterns
    scd2_pattern = [
        {"customer_id": 101, "name": "Alice", "valid_from": "2026-01-01", "valid_to": "2026-05-01", "is_current": 0},
        {"customer_id": 101, "name": "Alicia", "valid_from": "2026-05-02", "valid_to": "9999-12-31", "is_current": 1},
    ]
    
    # 9. Cleanse Only (whitespace / casing issues only)
    cleanse_only = [
        {"id": 1, "name": " ALICE ", "dept": "it"},
        {"id": 2, "name": "bob", "dept": "HR"},
    ]
    
    # 10. Transform Only (masking, ssn, credit card)
    transform_only = [
        {"id": 1, "name": "Alice", "ssn": "123-45-678", "credit_card": "1234-5678-9012-3456"},
        {"id": 2, "name": "Bob", "ssn": "987-65-432", "credit_card": "9876-5432-1098-7654"},
    ]
    
    # 11. Mixed DQ Rating
    mixed_dq = [
        {"id": 1, "name": "Alice", "score": "95"},
        {"id": 2, "name": "Bob", "score": "twenty"},  # Type mismatch
        {"id": 3, "name": None, "score": None},      # High nulls
    ]
    
    # 12. Force Unlock (extremely dirty data that requires unlock override)
    force_unlock = [
        {"id": None, "name": "  ", "email": "bad"},
        {"id": None, "name": "  ", "email": "bad2"},
    ]
    
    # 13. Suspicious Zeros
    suspicious_zeros = [
        {"id": 0, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]
    
    # 14. Near Duplicates
    near_duplicates = [
        {"id": 1, "name": "John Doe", "city": "New York"},
        {"id": 2, "name": "John Doe", "city": "New Yokr"}, # typo
        {"id": 3, "name": "Alice Smith", "city": "Los Angeles"},
    ]
    
    # 15. Multivariate Outliers
    multivariate_outliers = [
        {"id": 1, "x": 10, "y": 20},
        {"id": 2, "x": 12, "y": 22},
        {"id": 3, "x": 1000, "y": 2000}, # Extreme outlier
    ]
    
    # 16. Boolean Inconsistency
    boolean_inconsistency = [
        {"id": 1, "active": "true"},
        {"id": 2, "active": "yes"},
        {"id": 3, "active": "1"},
    ]
    
    # 17. Sentinel Values
    sentinel_values = [
        {"id": 1, "amount": 100},
        {"id": 2, "amount": -999}, # sentinel
    ]

    fixtures = {
        "happy_path.json": happy_path,
        "dirty_dates.json": dirty_dates,
        "dirty_emails.json": dirty_emails,
        "wide_table.json": wide_table,
        "null_primary_keys.json": null_pks,
        "fk_violations.json": fk_violations,
        "encoding_issues.json": encoding_issues,
        "scd2_pattern.json": scd2_pattern,
        "cleanse_only.json": cleanse_only,
        "transform_only.json": transform_only,
        "mixed_dq_rating.json": mixed_dq,
        "force_unlock.json": force_unlock,
        "suspicious_zeros.json": suspicious_zeros,
        "near_duplicates.json": near_duplicates,
        "multivariate_outliers.json": multivariate_outliers,
        "boolean_inconsistency.json": boolean_inconsistency,
        "sentinel_values.json": sentinel_values,
    }

    for fname, data in fixtures.items():
        path = os.path.join(fixtures_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"Created fixture: {path}")

if __name__ == "__main__":
    generate_fixtures()
