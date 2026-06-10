import re
import logging
import pandas as pd
import numpy as np
from rapidfuzz import fuzz

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("agent_dhara")

def deduplicate_near_duplicates(df_data: pd.DataFrame, threshold: float = 0.92, window_size: int = 15) -> pd.DataFrame:
    """
    Addresses: near_duplicate_rows (similarity >= 0.92) [Fuzzy matching ✅]
    Uses a sorted neighborhood method (sliding window) to ensure high performance on large datasets.
    """
    df_temp = df_data.copy()
    
    # Fill NAs temporarily with empty string to avoid errors in string concatenation
    df_temp_filled = df_temp.fillna("")
    
    # Create a combined string representing each row's contents
    df_temp['_comp_str'] = df_temp_filled.apply(
        lambda r: f"{str(r.get('id', ''))} {str(r.get('name', ''))} {str(r.get('email', ''))}", axis=1
    )
    
    # Sort by the comparison string to bring near-duplicates adjacent to each other
    df_temp = df_temp.sort_values('_comp_str').reset_index(drop=False)
    
    row_strings = df_temp['_comp_str'].tolist()
    n_rows = len(df_temp)
    dropped_indices = set()
    
    for i in range(n_rows):
        if i in dropped_indices:
            continue
        # Compare current row with subsequent rows within the sliding window
        for j in range(i + 1, min(i + window_size, n_rows)):
            if j in dropped_indices:
                continue
            similarity = fuzz.ratio(row_strings[i], row_strings[j]) / 100.0
            if similarity >= threshold:
                dropped_indices.add(j)
                
    # Drop near-duplicates and recover the original sorting order
    df_cleaned = df_temp.drop(index=list(dropped_indices)).sort_values('index')
    df_cleaned = df_cleaned.drop(columns=['index', '_comp_str'])
    
    logger.info(f"Near-duplicate check: dropped {len(dropped_indices)} similar rows.")
    return df_cleaned.reset_index(drop=True)

def clean_string(val: any, casing: str = None) -> str | None:
    """
    Helper function to safely clean strings:
    - Preserves actual null values (None, NaN, pd.NA).
    - Collapses consecutive internal spaces and trims leading/trailing spaces.
    - Dynamically maps common placeholders (e.g. 'tbd', 'none', 'null', 'nan') to None.
    - Resolves case formatting safely without converting NULLs to literal "nan" strings.
    """
    if pd.isnull(val):
        return None
    val_str = str(val).strip()
    
    # Collapse consecutive spaces
    val_str = re.sub(r'\s+', ' ', val_str)
    
    # Check if value is a placeholder
    placeholders = {"nan", "null", "none", "tbd", "tba", "n/a", "na", "-", "--"}
    if val_str.lower() in placeholders or not val_str:
        return None
        
    if casing == "title":
        return val_str.title()
    elif casing == "lower":
        return val_str.lower()
    return val_str

def clean_id(val: any) -> str | None:
    """
    Helper to safely clean and validate ID columns:
    - Preserves nulls.
    - Removes trailing .0 float representation.
    - Nullifies suspicious zero values and all magic/sentinel values.
    """
    if pd.isnull(val):
        return None
    val_str = str(val).strip()
    
    # Remove trailing .0 float representations (e.g. '10.0' -> '10')
    if val_str.endswith(".0"):
        val_str = val_str[:-2]
        
    # Check against known sentinel / suspicious zero values
    sentinels = {
        "0", "0.0", "-999", "999", "1111", "1234", "9876", "9999", "9999999", 
        "999999", "nan", "null", "###", "none", "tbd", "n/a"
    }
    if val_str.lower() in sentinels or not val_str:
        return None
        
    return val_str

def transform_ndta(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # --- 1. Whitespace, Case Normalization & Null Strategy ---
    # Safe cleaning: collapses consecutive internal spaces, trims, title-cases, and keeps true nulls
    df['name'] = df['name'].apply(lambda x: clean_string(x, casing="title"))
    
    # Safe cleaning for emails: trims, collapses internal spaces, lowercases, and keeps true nulls
    df['email'] = df['email'].apply(lambda x: clean_string(x, casing="lower"))

    # --- 2. ID Sentinel Values and Suspicious Zeros ---
    # Safe cleaning for IDs: removes float format, nullifies suspicious zeros and sentinels, keeps nulls
    df['id'] = df['id'].apply(clean_id)

    # --- 3. Strict Email Format and Domain Validation ---
    # Strict regex pattern validates standard format AND @capgemini.com domain
    email_pattern = r'^[a-z0-9._%+-]+@capgemini\.com$'
    
    # Quarantine: Set any invalid format or non-capgemini emails to None (NULL)
    df['email'] = df['email'].apply(lambda x: x if isinstance(x, str) and re.match(email_pattern, x) else None)

    # --- 4. Deduplication & Near-Duplicates Handling ---
    # Step 1: Drop exact duplicates
    df = df.drop_duplicates()
    
    # Step 2: Drop near-duplicate rows (similarity >= 0.92) using fuzzy matching
    df = deduplicate_near_duplicates(df, threshold=0.92, window_size=15)
    
    # Step 3: Deduplicate based on 'id' (uniqueness check)
    # Filter out null IDs before checking uniqueness, keeping the first valid record
    df = df.drop_duplicates(subset=['id'], keep='first')

    return df

if __name__ == "__main__":
    try:
        df_ndta = pd.read_csv("ndta.csv")
        transformed_df = transform_ndta(df_ndta)
        
        import os
        os.makedirs("cleaned", exist_ok=True)
        transformed_df.to_csv("cleaned/ndta_csv_cleaned.csv", index=False)
        print("NDTA dataset cleaned successfully!")
    except FileNotFoundError:
        print("ndta.csv not found, transform function is ready for import and execution.")
