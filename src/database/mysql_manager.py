import aiomysql
import os
from datetime import datetime

class MySQLManager:
    def __init__(self):
        self.host = os.getenv("MYSQL_HOST", "db")
        self.user = os.getenv("MYSQL_USER", "kaptango_user")
        self.password = os.getenv("MYSQL_PASSWORD", "kaptango_password")
        self.db = os.getenv("MYSQL_DATABASE", "kaptango")

    async def get_connection(self):
        return await aiomysql.connect(
            host=self.host,
            user=self.user,
            password=self.password,
            db=self.db
        )

    async def init_db(self):
        retries = 5
        while retries > 0:
            try:
                conn = await self.get_connection()
                async with conn.cursor() as cur:
                    # Calls table with duration and timing
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS calls (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            call_sid VARCHAR(255) UNIQUE,
                            stream_sid VARCHAR(255),
                            phone_number VARCHAR(20),
                            result VARCHAR(50),
                            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            ended_at TIMESTAMP NULL,
                            duration INT DEFAULT 0,
                            INDEX idx_phone (phone_number),
                            INDEX idx_created (started_at)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                    """)
                    
                    # Migration: Add columns if they don't exist
                    await cur.execute("SHOW COLUMNS FROM calls")
                    columns = [col[0] for col in await cur.fetchall()]
                    
                    if 'duration' not in columns:
                        await cur.execute("ALTER TABLE calls ADD COLUMN duration INT DEFAULT 0")
                    if 'started_at' not in columns:
                        if 'created_at' in columns:
                            await cur.execute("ALTER TABLE calls CHANGE COLUMN created_at started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                        else:
                            await cur.execute("ALTER TABLE calls ADD COLUMN started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                    if 'ended_at' not in columns:
                        await cur.execute("ALTER TABLE calls ADD COLUMN ended_at TIMESTAMP NULL")

                    # Transcripts table
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS transcripts (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            call_id INT,
                            role ENUM('user', 'assistant') NOT NULL,
                            content TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE CASCADE,
                            INDEX idx_call_id (call_id)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                    """)
                await conn.commit()
                conn.close()
                print("Database initialized successfully with performance indices.")
                return
            except Exception as e:
                print(f"Database initialization failed: {e}. Retrying in 5 seconds... ({retries} retries left)")
                await asyncio.sleep(5)
                retries -= 1
        raise Exception("Could not initialize database after multiple retries.")

    async def start_call(self, call_sid, stream_sid, phone_number):
        conn = await self.get_connection()
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO calls (call_sid, stream_sid, phone_number, started_at) VALUES (%s, %s, %s, NOW())",
                (call_sid, stream_sid, phone_number)
            )
            call_id = cur.lastrowid
        await conn.commit()
        conn.close()
        return call_id

    async def update_call_status(self, call_id, result):
        conn = await self.get_connection()
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE calls SET ended_at = NOW(), duration = TIMESTAMPDIFF(SECOND, started_at, NOW()), result = %s WHERE id = %s",
                (result, call_id)
            )
        await conn.commit()
        conn.close()

    async def add_transcript(self, call_id, role, content):
        conn = await self.get_connection()
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO transcripts (call_id, role, content) VALUES (%s, %s, %s)",
                (call_id, role, content)
            )
        await conn.commit()
        conn.close()

    async def get_stats(self):
        conn = await self.get_connection()
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT COUNT(*) as total_calls FROM calls")
            total = await cur.fetchone()
            await cur.execute("SELECT COUNT(*) as interested_calls FROM calls WHERE result = 'Interested'")
            interested = await cur.fetchone()
            await cur.execute("SELECT AVG(duration) as avg_duration FROM calls WHERE duration > 0")
            avg = await cur.fetchone()
        conn.close()
        return {
            "total_calls": total['total_calls'],
            "interested_calls": interested['interested_calls'],
            "avg_duration": round(avg['avg_duration'] or 0, 2)
        }

    async def get_calls(self, limit=50):
        conn = await self.get_connection()
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM calls ORDER BY started_at DESC LIMIT %s", (limit,))
            calls = await cur.fetchall()
        conn.close()
        return calls

    async def get_call_detail(self, call_id):
        conn = await self.get_connection()
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM calls WHERE id = %s", (call_id,))
            call = await cur.fetchone()
            if call:
                await cur.execute("SELECT role, content, created_at FROM transcripts WHERE call_id = %s ORDER BY created_at ASC", (call_id,))
                call['transcript'] = await cur.fetchall()
        conn.close()
        return call

db_manager = MySQLManager()
