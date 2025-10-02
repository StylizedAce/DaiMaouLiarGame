"""
Utility functions for the Dai Maou Liar Game.
Contains question handling, validation, and other helper functions.
"""

import pandas as pd
import random


def get_question_pair(used_indexes=None, language='en'):
    """Returns a single random question pair (normal, imposter) and its index."""
    if used_indexes is None:
        used_indexes = []
    
    print(f"🔍 get_question_pair called with language: {language}")
    print(f"🔍 used_indexes received: {used_indexes}")
    
    try:
        # Select CSV file based on language
        csv_file = 'question_pairs_ar.csv' if language == 'ar' else 'question_pairs.csv'
        print(f"🔍 Loading CSV file: {csv_file}")
        
        df = pd.read_csv(csv_file)
        if df.empty:
            raise ValueError(f"{csv_file} is empty.")
        
        all_indexes = list(range(len(df)))
        available_indexes = [i for i in all_indexes if i not in used_indexes]
        
        print(f"🔍 Total questions in CSV: {len(all_indexes)}")
        print(f"🔍 Available indexes after filtering: {available_indexes}")
        
        if not available_indexes:
            print("⚠️ WARNING: All questions used. Resetting pool.")
            available_indexes = all_indexes
        
        selected_index = random.choice(available_indexes)
        row = df.iloc[selected_index]
        question_pair = (row['Normal_Question'], row['Imposter_Question'])
        
        print(f"✅ Selected question index {selected_index}: {question_pair[0][:50]}...")
        
        return (question_pair[0], question_pair[1], selected_index)
        
    except Exception as e:
        print(f"❌ ERROR: Could not load {csv_file} ({e}). Using default pairs.")
        return None
        
def validate_room_data(data, required_fields):
    """
    Validates that required fields are present in the provided data.
    
    Args:
        data (dict): The data to validate
        required_fields (list): List of required field names
    
    Returns:
        tuple: (is_valid, missing_fields)
    """
    missing_fields = [field for field in required_fields if not data.get(field)]
    return len(missing_fields) == 0, missing_fields


def sanitize_string(input_string, max_length=100):
    """
    Sanitizes user input strings by trimming whitespace and limiting length.
    
    Args:
        input_string (str): The string to sanitize
        max_length (int): Maximum allowed length
    
    Returns:
        str: The sanitized string
    """
    if not isinstance(input_string, str):
        return ""
    
    sanitized = input_string.strip()
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    
    return sanitized


def is_name_available(players_list, name):
    """
    Checks if a name is available in a list of players.
    
    Args:
        players_list (list): List of player dictionaries
        name (str): The name to check
    
    Returns:
        bool: True if name is available, False otherwise
    """
    return not any(p["name"] == name for p in players_list)


def get_active_players(players_list):
    """
    Returns only the active (non-disconnected) players from a list.
    
    Args:
        players_list (list): List of player dictionaries
    
    Returns:
        list: List of active players
    """
    return [p for p in players_list if not p.get("disconnected")]
