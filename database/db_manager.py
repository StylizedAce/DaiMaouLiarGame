"""
Database operations module for the Dai Maou Liar Game.
Handles SQLite database initialization, room CRUD operations, and cleanup.
"""

import sqlite3
import json
import os
import atexit


class DatabaseManager:
    """Manages SQLite database operations for game rooms."""
    
    def __init__(self, db_path='game_rooms.db'):
        self.DB_PATH = db_path
        self.init_database()
        # Register cleanup function to run on shutdown
        atexit.register(self.cleanup_database)
    
    def init_database(self):
        """Initialize the SQLite database with required tables."""
        conn = sqlite3.connect(self.DB_PATH)
        cursor = conn.cursor()
        
        # Create rooms table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY,
                players TEXT NOT NULL,  -- JSON string
                host_id TEXT NOT NULL,
                phase TEXT NOT NULL DEFAULT 'waiting',
                imposter_id TEXT,
                roles TEXT,  -- JSON string
                questions TEXT,  -- JSON string
                answers TEXT,  -- JSON string
                votes TEXT,  -- JSON string
                results TEXT,  -- JSON string
                lobby_events TEXT,  -- JSON string
                main_question TEXT,
                ready_to_vote TEXT,  -- JSON string
                settings TEXT,  -- JSON string
                question_phase_start_timestamp INTEGER,
                voting_phase_start_timestamp INTEGER,
                vote_selection_start_timestamp INTEGER,
                liar_votes TEXT,  -- JSON string
                used_question_indexes TEXT,  -- JSON string
                current_round INTEGER DEFAULT 1,
                total_rounds INTEGER DEFAULT 5
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def cleanup_database(self):
        """Remove the database file on shutdown for fresh slate."""
        if os.path.exists(self.DB_PATH):
            os.remove(self.DB_PATH)
            print("Database cleaned up for fresh slate.")
    
    def get_connection(self):
        """Get a database connection."""
        conn = sqlite3.connect(self.DB_PATH)
        conn.row_factory = sqlite3.Row  # This enables column access by name
        return conn
    
    def create_room(self, room_id, room_data):
        """Create a new room in the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO rooms (
                room_id, players, host_id, phase, imposter_id, roles, questions,
                answers, votes, results, lobby_events, main_question, ready_to_vote,
                settings, question_phase_start_timestamp, voting_phase_start_timestamp,
                vote_selection_start_timestamp, liar_votes, used_question_indexes,
                current_round, total_rounds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            room_id,
            json.dumps(room_data.get('players', [])),
            room_data.get('host_id', ''),
            room_data.get('phase', 'waiting'),
            room_data.get('imposter_id'),
            json.dumps(room_data.get('roles', {})),
            json.dumps(room_data.get('questions', {})),
            json.dumps(room_data.get('answers', {})),
            json.dumps(room_data.get('votes', {})),
            json.dumps(room_data.get('results', {})),
            json.dumps(room_data.get('lobby_events', [])),
            room_data.get('main_question'),
            json.dumps(room_data.get('ready_to_vote', [])),
            json.dumps(room_data.get('settings', {})),
            room_data.get('questionPhaseStartTimestamp'),
            room_data.get('votingPhaseStartTimestamp'),
            room_data.get('voteSelectionStartTimestamp'),
            json.dumps(room_data.get('liarVotes', {})),
            json.dumps(room_data.get('used_question_indexes', [])),
            room_data.get('current_round', 1),
            room_data.get('total_rounds', 5)
        ))
        
        conn.commit()
        conn.close()
    
    def get_room(self, room_id):
        """Get a room from the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM rooms WHERE room_id = ?', (room_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        # Convert back to dictionary format
        room_data = {
            'players': json.loads(row['players']),
            'host_id': row['host_id'],
            'phase': row['phase'],
            'imposter_id': row['imposter_id'],
            'roles': json.loads(row['roles']),
            'questions': json.loads(row['questions']),
            'answers': json.loads(row['answers']),
            'votes': json.loads(row['votes']),
            'results': json.loads(row['results']),
            'lobby_events': json.loads(row['lobby_events']),
            'main_question': row['main_question'],
            'ready_to_vote': json.loads(row['ready_to_vote']),
            'settings': json.loads(row['settings']),
            'questionPhaseStartTimestamp': row['question_phase_start_timestamp'],
            'votingPhaseStartTimestamp': row['voting_phase_start_timestamp'],
            'voteSelectionStartTimestamp': row['vote_selection_start_timestamp'],
            'liarVotes': json.loads(row['liar_votes']),
            'used_question_indexes': json.loads(row['used_question_indexes']),
            'current_round': row['current_round'],
            'total_rounds': row['total_rounds']
        }
        
        return room_data
    
    def update_room(self, room_id, room_data):
        """Update a room in the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE rooms SET
                players = ?, host_id = ?, phase = ?, imposter_id = ?, roles = ?,
                questions = ?, answers = ?, votes = ?, results = ?, lobby_events = ?,
                main_question = ?, ready_to_vote = ?, settings = ?,
                question_phase_start_timestamp = ?, voting_phase_start_timestamp = ?,
                vote_selection_start_timestamp = ?, liar_votes = ?, used_question_indexes = ?,
                current_round = ?, total_rounds = ?
            WHERE room_id = ?
        ''', (
            json.dumps(room_data.get('players', [])),
            room_data.get('host_id', ''),
            room_data.get('phase', 'waiting'),
            room_data.get('imposter_id'),
            json.dumps(room_data.get('roles', {})),
            json.dumps(room_data.get('questions', {})),
            json.dumps(room_data.get('answers', {})),
            json.dumps(room_data.get('votes', {})),
            json.dumps(room_data.get('results', {})),
            json.dumps(room_data.get('lobby_events', [])),
            room_data.get('main_question'),
            json.dumps(room_data.get('ready_to_vote', [])),
            json.dumps(room_data.get('settings', {})),
            room_data.get('questionPhaseStartTimestamp'),
            room_data.get('votingPhaseStartTimestamp'),
            room_data.get('voteSelectionStartTimestamp'),
            json.dumps(room_data.get('liarVotes', {})),
            json.dumps(room_data.get('used_question_indexes', [])),
            room_data.get('current_round', 1),
            room_data.get('total_rounds', 5),
            room_id
        ))
        
        conn.commit()
        conn.close()
    
    def delete_room(self, room_id):
        """Delete a room from the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM rooms WHERE room_id = ?', (room_id,))
        
        conn.commit()
        conn.close()
    
    def get_all_room_ids(self):
        """Get all room IDs from the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT room_id FROM rooms')
        rows = cursor.fetchall()
        conn.close()
        
        return [row['room_id'] for row in rows]
    
    def room_exists(self, room_id):
        """Check if a room exists in the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT 1 FROM rooms WHERE room_id = ?', (room_id,))
        exists = cursor.fetchone() is not None
        conn.close()
        
        return exists
