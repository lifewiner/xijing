"""
数据管理模块 - 负责用户数据的存储、读取和统计分析
"""
import json
import os
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import hashlib


class DataManager:
    def __init__(self, db_path: str = "data_literacy.db"):
        """初始化数据管理器"""
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 用户基本信息表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                grade TEXT,
                major TEXT,
                data_exp TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id)
            )
        ''')

        # 测评结果表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS assessments (
                assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_score REAL,
                scores_json TEXT,
                score_rates_json TEXT,
                answers_json TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        # 详细得分表（可选，用于更详细的分析）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS assessment_details (
                detail_id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER,
                dimension_code TEXT,
                question_index INTEGER,
                question_text TEXT,
                user_score INTEGER,
                max_score REAL,
                actual_score REAL,
                FOREIGN KEY (assessment_id) REFERENCES assessments (assessment_id)
            )
        ''')

        conn.commit()
        conn.close()

    def save_assessment(self, session_id: str, user_info: Dict,
                        answers: List[List[int]], total_score: float,
                        scores: List[float], score_rates: List[float]) -> int:
        """保存测评结果"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # 1. 保存或获取用户信息
            cursor.execute(
                "SELECT user_id FROM users WHERE session_id = ?",
                (session_id,)
            )
            result = cursor.fetchone()

            if result:
                user_id = result[0]
                # 更新用户信息
                cursor.execute('''
                    UPDATE users 
                    SET grade = ?, major = ?, data_exp = ?
                    WHERE user_id = ?
                ''', (user_info.get('grade'), user_info.get('major'),
                      user_info.get('data_exp'), user_id))
            else:
                cursor.execute('''
                    INSERT INTO users (session_id, grade, major, data_exp)
                    VALUES (?, ?, ?, ?)
                ''', (session_id, user_info.get('grade'),
                      user_info.get('major'), user_info.get('data_exp')))
                user_id = cursor.lastrowid

            # 2. 保存测评结果
            cursor.execute('''
                INSERT INTO assessments 
                (user_id, total_score, scores_json, score_rates_json, answers_json)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                user_id,
                total_score,
                json.dumps(scores),
                json.dumps(score_rates),
                json.dumps(answers)
            ))

            assessment_id = cursor.lastrowid

            conn.commit()
            return assessment_id

        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def get_all_assessments(self) -> pd.DataFrame:
        """获取所有测评数据"""
        conn = sqlite3.connect(self.db_path)

        query = '''
            SELECT 
                u.user_id,
                u.session_id,
                u.grade,
                u.major,
                u.data_exp,
                u.created_at as user_created,
                a.assessment_id,
                a.timestamp,
                a.total_score,
                a.scores_json,
                a.score_rates_json,
                a.answers_json
            FROM users u
            JOIN assessments a ON u.user_id = a.user_id
            ORDER BY a.timestamp DESC
        '''

        df = pd.read_sql_query(query, conn)
        conn.close()

        # 解析JSON字段
        if not df.empty:
            df['scores'] = df['scores_json'].apply(json.loads)
            df['score_rates'] = df['score_rates_json'].apply(json.loads)
            df['answers'] = df['answers_json'].apply(json.loads)

            # 添加维度得分列
            dimension_names = ['C1', 'C2', 'C3', 'C4', 'C5', 'C6']
            for i, dim in enumerate(dimension_names):
                df[f'score_{dim}'] = df['scores'].apply(lambda x: x[i] if i < len(x) else 0)
                df[f'rate_{dim}'] = df['score_rates'].apply(lambda x: x[i] if i < len(x) else 0)

        return df

    def get_assessment_stats(self) -> Dict:
        """获取测评统计信息"""
        df = self.get_all_assessments()

        if df.empty:
            return {}

        stats = {
            'total_assessments': len(df),
            'total_users': df['user_id'].nunique(),
            'avg_total_score': df['total_score'].mean(),
            'min_total_score': df['total_score'].min(),
            'max_total_score': df['total_score'].max(),
            'std_total_score': df['total_score'].std(),
            'recent_7days': len(
                df[df['timestamp'] > (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')]),
            'recent_30days': len(
                df[df['timestamp'] > (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')]),
        }

        # 维度统计
        dimension_names = ['C1', 'C2', 'C3', 'C4', 'C5', 'C6']
        for dim in dimension_names:
            score_col = f'score_{dim}'
            rate_col = f'rate_{dim}'
            if score_col in df.columns:
                stats[f'avg_score_{dim}'] = df[score_col].mean()
                stats[f'avg_rate_{dim}'] = df[rate_col].mean()

        return stats

    def get_dimension_analysis(self) -> pd.DataFrame:
        """获取各维度详细分析"""
        df = self.get_all_assessments()

        if df.empty:
            return pd.DataFrame()

        dimension_names = ['C1:数据认知与采集', 'C2:数据处理与分析',
                           'C3:数据存储与验证', 'C4:数据表达与交流',
                           'C5:数据践行', 'C6:数据道德']

        results = []
        for i, dim_name in enumerate(dimension_names):
            dim_code = f'C{i + 1}'
            score_col = f'score_{dim_code}'
            rate_col = f'rate_{dim_code}'

            if score_col in df.columns:
                results.append({
                    '维度': dim_name,
                    '维度代码': dim_code,
                    '平均得分': df[score_col].mean(),
                    '得分标准差': df[score_col].std(),
                    '平均得分率': df[rate_col].mean(),
                    '最低得分': df[score_col].min(),
                    '最高得分': df[score_col].max(),
                    '中位数得分': df[score_col].median(),
                    '测评人数': len(df[score_col].dropna())
                })

        return pd.DataFrame(results)

    def get_demographic_analysis(self, by_field: str = 'major') -> pd.DataFrame:
        """按人口统计字段进行分析"""
        df = self.get_all_assessments()

        if df.empty or by_field not in df.columns:
            return pd.DataFrame()

        analysis = df.groupby(by_field).agg({
            'total_score': ['count', 'mean', 'std', 'min', 'max'],
            'user_id': 'nunique'
        }).round(2)

        analysis.columns = ['测评次数', '平均得分', '得分标准差', '最低得分', '最高得分', '独立用户数']
        analysis = analysis.sort_values('平均得分', ascending=False)

        return analysis

    def get_temporal_analysis(self) -> pd.DataFrame:
        """时间趋势分析"""
        df = self.get_all_assessments()

        if df.empty:
            return pd.DataFrame()

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['date'] = df['timestamp'].dt.date
        df['week'] = df['timestamp'].dt.isocalendar().week
        df['month'] = df['timestamp'].dt.to_period('M')

        # 按日统计
        daily_stats = df.groupby('date').agg({
            'assessment_id': 'count',
            'total_score': 'mean'
        }).rename(columns={'assessment_id': '测评次数', 'total_score': '平均得分'})

        return daily_stats

    def clear_test_data(self):
        """清除测试数据（仅用于开发）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM assessment_details")
        cursor.execute("DELETE FROM assessments")
        cursor.execute("DELETE FROM users")
        conn.commit()
        conn.close()