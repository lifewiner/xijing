# -*- coding: utf-8 -*-
"""
大学生数据素养测评系统 - 完整优化版
一键运行：streamlit run streamlit_app.py
"""

# 1. 导入streamlit并立即设置页面配置
import streamlit as st

st.set_page_config(
    page_title='大学生数据素养测评系统',
    page_icon='📊',
    layout='wide',
    initial_sidebar_state='expanded'
)

# 2. 然后导入其他库
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import json
import sqlite3
import uuid

# 3. 设置matplotlib中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Heiti SC', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


# ----------------- 数据管理类 -----------------
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

        conn.commit()
        conn.close()

    def save_assessment(self, session_id: str, user_info: dict,
                        answers: list, total_score: float,
                        scores: list, score_rates: list) -> int:
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
            st.error(f"保存数据时出错: {str(e)}")
            return None
        finally:
            conn.close()

    @st.cache_data(ttl=300)  # 缓存5分钟
    def get_all_assessments(_self) -> pd.DataFrame:
        """获取所有测评数据"""
        conn = sqlite3.connect(_self.db_path)

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

        try:
            df = pd.read_sql_query(query, conn)

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
        except Exception as e:
            st.error(f"读取数据时出错: {str(e)}")
            return pd.DataFrame()
        finally:
            conn.close()

    def get_assessment_stats(self) -> dict:
        """获取测评统计信息"""
        df = self.get_all_assessments()

        if df.empty:
            return {}

        # 计算时间相关的统计
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        # 将字符串时间转换为datetime对象
        df['timestamp_dt'] = pd.to_datetime(df['timestamp'])

        stats = {
            'total_assessments': len(df),
            'total_users': df['user_id'].nunique(),
            'avg_total_score': float(df['total_score'].mean()),
            'min_total_score': float(df['total_score'].min()),
            'max_total_score': float(df['total_score'].max()),
            'std_total_score': float(df['total_score'].std()),
            'recent_7days': int(len(df[df['timestamp_dt'] > week_ago])),
            'recent_30days': int(len(df[df['timestamp_dt'] > month_ago])),
        }

        return stats


# ----------------- 题库数据 -----------------
# 一级指标与权重
C = pd.DataFrame({
    '维度': ['C1:数据认知与采集', 'C2:数据处理与分析', 'C3:数据存储与验证',
             'C4:数据表达与交流', 'C5:数据践行', 'C6:数据道德'],
    '权重': [0.3339, 0.2361, 0.1214, 0.1214, 0.1157, 0.0715]
})
C['权重'] = C['权重'] / C['权重'].sum()

# 题库
题库 = {
    'C1': {
        'Question': [
            '01. 在不同阶段，能够清晰分辨自己的数据需求并将其明确表述',
            '02. 在学习工作中，养成通过数据方法解决问题的基本习惯',
            '03. 对数据价值有较高的敏感性并能抓取数据背后含义、过滤无用数据',
            '04. 对元数据等数据相关概念有一定理解，有较深的数学、统计学知识储备',
            '05. 具备基本的数据检索知识和能力，掌握基本数据检索方法（布尔逻辑算法、关键词换组等）和搜索引擎使用方法，能准确识别数据源',
            '06. 可以使用大于等于一种的数据采集工具（如爬虫软件）',
            '07. 能够通过关联字段筛选提取所需数据，并能简单使用数据库提取'
        ],
        'Score': [1.9, 1.5, 1.8, 3.2, 12.0, 7.5, 5.6]
    },
    'C2': {
        'Question': [
            '08. 能较为熟练地使用数据清洗、分类、转变和取值等方法处理数据',
            '09. 能够及时对可疑数据进行核对，对残缺丢失的数据进行修补、恢复，判断"脏数据"中的无用数据进行删除',
            '10. 可以通过一定的算法完成对数据的计算',
            '11. 最少熟练使用一种数据处理与分析工具并能了解多种数据分析工具（如EXCEL、SPSS、Matlab）',
            '12. 关注重要数据、养成记忆数据的习惯，具备大数据思维和基本的数据分析的思维，能分析出数据背后的含义',
            '13. 较为准确客观地完成对得出的数据结论的解读',
            '14. 根据数据处理分析的结论来完成所需作品'
        ],
        'Score': [4.8, 2.7, 4.7, 3.9, 2.1, 2.6, 2.9]
    },
    'C3': {
        'Question': [
            '15. 可以使用不同数据库对数据进行分类保存，使用硬盘、U盘等硬件存储或者百度云盘等设备存储数据',
            '16. 具备基本的数据安全保护意识，随时备份，及时辨别数据环境的安全情况，使用杀毒软件等工具保护自己的数据隐私',
            '17. 能对手中存储的数据进行统一归档、分类、标注',
            '18. 以批判思维对各流程数据，客观公正地评价数据分析成果',
            '19. 能对各流程所得出的结论进行有效校对和测试'
        ],
        'Score': [2.5, 3.4, 3.8, 1.4, 1.1]
    },
    'C4': {
        'Question': [
            '20. 使用可视化软件（PPT等）以图表等形式展现得出的成果',
            '21. 能概括数据分析后的核心观点、成果，并以数据化语言表述',
            '22. 能使用数据分析处理后的成果，撰写工作报告或学术论文',
            '23. 通过不同媒介分享数据成果，以数据的形式与其他主体交流'
        ],
        'Score': [2.4, 2.4, 6.3, 1.0]
    },
    'C5': {
        'Question': [
            '24. 对项目有深刻的理解，完成问题量化定义，掌握项目各阶段的数据工作',
            '25. 针对不同的问题进行差异性数据流程和方法组合，利用数据构造产出成果框架和内涵，并通过产出成果与需求的匹配，进行成果优化',
            '26. 用言简意赅的数据结论和便于理解的方式（比喻、举例等）与业务相关方沟通',
            '27. 在业务理解基础上，以数据意见形式推动业务落地转化为具体成果'
        ],
        'Score': [3.8, 1.9, 1.7, 4.2]
    },
    'C6': {
        'Question': [
            '28. 能够重视和保护相关各方的数据隐私',
            '29. 了解相关的数据安全、知识产权法规，严格遵守知识产权法',
            '30. 有严格的数据自律性，不随意篡改数据，能以正确的方式引用和使用数据'
        ],
        'Score': [3.5, 1.4, 2.2]
    }
}


# ----------------- 初始化数据管理器 -----------------
@st.cache_resource
def get_data_manager():
    return DataManager()


data_manager = get_data_manager()


# ----------------- 工具函数 -----------------
def calc_scores(all_answers):
    """计算得分"""
    scores, score_rates = [], []
    for i, code in enumerate(题库.keys()):
        full = np.array(题库[code]['Score'])
        ans = np.array(all_answers[i])
        got = ans * full / 6
        scores.append(got.sum())
        score_rates.append(got.sum() / full.sum() * 100)
    total = np.dot(scores, C['权重'].values)
    return total, scores, score_rates


def generate_session_id():
    """生成用户会话ID"""
    if 'session_id' not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    return st.session_state.session_id


# ----------------- 页面函数 -----------------
def show_weight_page():
    """显示权重页面"""
    st.header('📊 数据素养指标权重')

    col1, col2 = st.columns(2)
    with col1:
        fig, ax = plt.subplots(figsize=(10, 6))
        bars = ax.bar(C['维度'], C['权重'], color=plt.cm.Set3(range(len(C))))
        ax.set_ylabel('权重', fontsize=12)
        ax.set_title('各维度权重分布', fontsize=14)
        plt.xticks(rotation=45, ha='right')

        # 在柱子上显示权重值
        for bar, weight in zip(bars, C['权重']):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2., height + 0.01,
                    f'{weight:.3f}', ha='center', va='bottom')

        st.pyplot(fig)
        plt.close(fig)

    with col2:
        fig, ax = plt.subplots(figsize=(8, 8))
        colors = plt.cm.Paired(range(len(C)))
        wedges, texts, autotexts = ax.pie(C['权重'], labels=C['维度'],
                                          autopct='%1.1f%%', startangle=90,
                                          colors=colors)

        # 美化饼图
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontsize(10)

        ax.set_title('权重比例图', fontsize=14)
        st.pyplot(fig)
        plt.close(fig)

    # 显示权重表格
    st.subheader("权重详情")
    weight_df = C.copy()
    weight_df['权重百分比'] = (weight_df['权重'] * 100).round(2).astype(str) + '%'
    st.dataframe(weight_df[['维度', '权重', '权重百分比']], use_container_width=True)


def show_test_page():
    """显示测评页面"""
    st.header('📝 数据素养测评')

    # 用户信息收集
    st.subheader("👤 个人信息")
    col1, col2, col3 = st.columns(3)
    with col1:
        grade = st.selectbox("年级", ["请选择", "大一", "大二", "大三", "大四", "研究生", "其他"])
    with col2:
        major = st.selectbox("专业类别", [
            "请选择", "理工类", "经管类", "人文社科类", "艺术类", "医学类", "其他"
        ])
    with col3:
        data_exp = st.selectbox("数据相关经验", [
            "请选择", "无经验", "少量课程学习", "参加过相关培训", "有项目经验", "专业领域经验丰富"
        ])

    # 检查是否填写完整
    if grade == "请选择" or major == "请选择" or data_exp == "请选择":
        st.warning("请先完善个人信息")
        return

    # 保存用户信息
    user_info = {
        'grade': grade,
        'major': major,
        'data_exp': data_exp
    }
    st.session_state.user_info = user_info

    # 初始化答案存储
    if 'answers' not in st.session_state:
        st.session_state.answers = [[] for _ in 题库]

    # 创建标签页
    tabs = st.tabs([f"{dim}" for dim in C['维度']])

    # 进度追踪
    total_questions = sum(len(题库[code]['Question']) for code in 题库)
    answered = 0

    # 每个维度的题目
    for i, (code, tab) in enumerate(zip(题库.keys(), tabs)):
        with tab:
            st.markdown(f"### {C.iloc[i]['维度']}")
            st.caption(f"本维度共 {len(题库[code]['Question'])} 题")

            ans = []
            for j, q in enumerate(题库[code]['Question']):
                # 使用滑动条，显示标签
                answer = st.slider(
                    f'{q}',
                    min_value=1,
                    max_value=6,
                    value=3,
                    step=1,
                    key=f'{code}_{j}',
                    help="1分: 完全不符合, 6分: 完全符合"
                )
                ans.append(answer)

                # 记录已回答的题目
                if answer != 3:  # 3是默认值
                    answered += 1

            st.session_state.answers[i] = ans

    # 显示进度条
    progress = answered / total_questions
    st.progress(progress)
    st.caption(f"📊 完成进度: {answered}/{total_questions} 题 ({progress:.1%})")

    # 提交按钮
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button('🚀 提交测评', type='primary', use_container_width=True):
            # 计算得分
            total, scores, rates = calc_scores(st.session_state.answers)

            # 保存到数据库
            session_id = generate_session_id()
            assessment_id = data_manager.save_assessment(
                session_id=session_id,
                user_info=user_info,
                answers=st.session_state.answers,
                total_score=total,
                scores=scores,
                score_rates=rates
            )

            if assessment_id:
                # 保存到session state
                st.session_state.current_result = {
                    'total_score': total,
                    'scores': scores,
                    'score_rates': rates,
                    'assessment_id': assessment_id
                }
                st.session_state.test_completed = True

                st.success('✅ 测评提交成功！请前往"查看结果"页面查看您的测评结果。')
                st.balloons()
                st.rerun()
            else:
                st.error("保存测评结果失败，请重试。")


def show_result_page():
    """显示个人结果页面"""
    st.header('📈 个人测评结果')

    if not st.session_state.get('test_completed', False):
        st.warning('请先完成测评！')
        return

    result = st.session_state.get('current_result', {})
    if not result:
        st.error('未找到测评结果')
        return

    total = result['total_score']
    scores = result['scores']
    rates = result['score_rates']

    # 计算满分
    max_total = sum(np.array(题库[code]['Score']).sum() * C.loc[i, '权重']
                    for i, code in enumerate(题库))

    # 显示关键指标
    col1, col2, col3, col4 = st.columns(4)
    col1.metric('综合得分', f'{total:.2f}')
    col2.metric('满分', f'{max_total:.2f}')
    col3.metric('得分率', f'{total / max_total * 100:.2f}%')
    col4.metric('评估状态', '已完成')

    # 各维度得分
    st.subheader('📊 各维度表现')

    col1, col2 = st.columns(2)

    with col1:
        # 得分柱状图
        fig, ax = plt.subplots(figsize=(10, 6))
        bars = ax.bar(C['维度'], scores, color=plt.cm.Blues(np.linspace(0.4, 0.8, len(scores))))
        ax.set_ylabel('得分', fontsize=12)
        ax.set_title('各维度得分', fontsize=14)
        plt.xticks(rotation=45, ha='right')

        # 在柱子上显示得分
        for bar, score in zip(bars, scores):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2., height + 0.1,
                    f'{score:.1f}', ha='center', va='bottom')

        st.pyplot(fig)
        plt.close(fig)

    with col2:
        # 得分率柱状图
        fig, ax = plt.subplots(figsize=(10, 6))
        bars = ax.bar(C['维度'], rates, color=plt.cm.Greens(np.linspace(0.4, 0.8, len(rates))))
        ax.set_ylabel('得分率 (%)', fontsize=12)
        ax.set_title('各维度得分率', fontsize=14)
        ax.set_ylim(0, 100)
        plt.xticks(rotation=45, ha='right')

        # 在柱子上显示得分率
        for bar, rate in zip(bars, rates):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2., height + 1,
                    f'{rate:.1f}%', ha='center', va='bottom')

        st.pyplot(fig)
        plt.close(fig)

    # 详细得分表
    st.subheader('📋 详细得分')
    detail_data = []
    for i, code in enumerate(题库.keys()):
        for j, q in enumerate(题库[code]['Question']):
            answer = st.session_state.answers[i][j] if i < len(st.session_state.answers) and j < len(
                st.session_state.answers[i]) else 3
            max_score = 题库[code]['Score'][j]
            actual_score = answer * max_score / 6

            detail_data.append({
                '维度': C.iloc[i]['维度'],
                '问题编号': f"{code}-{j + 1:02d}",
                '问题描述': q,
                '自我评分': answer,
                '满分': max_score,
                '实际得分': round(actual_score, 2)
            })

    detail_df = pd.DataFrame(detail_data)
    st.dataframe(detail_df, use_container_width=True)

    # 下载按钮
    csv = detail_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label='📥 下载详细结果 (CSV)',
        data=csv,
        file_name=f'数据素养测评_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv',
        mime='text/csv'
    )

    # 改进建议
    st.subheader('💡 提升建议')

    # 找出最低分的维度
    min_rate_idx = np.argmin(rates) if rates else 0
    weakest_dim = C.iloc[min_rate_idx]['维度'] if min_rate_idx < len(C) else C.iloc[0]['维度']

    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**最需要提升的维度：** {weakest_dim}")
        if rates:
            st.write(f"该维度得分率：{rates[min_rate_idx]:.1f}%")

        # 给出建议
        suggestions = {
            'C1:数据认知与采集': [
                "加强数据需求识别能力训练",
                "学习数据检索方法和技巧",
                "掌握基本的数据采集工具使用"
            ],
            'C2:数据处理与分析': [
                "学习数据清洗和处理方法",
                "掌握Excel或SPSS等数据分析工具",
                "培养数据分析思维"
            ],
            'C3:数据存储与验证': [
                "建立数据备份习惯",
                "学习数据验证和校对方法",
                "增强数据安全意识"
            ],
            'C4:数据表达与交流': [
                "学习数据可视化方法",
                "提升数据报告撰写能力",
                "加强数据沟通技巧"
            ],
            'C5:数据践行': [
                "加强项目中的数据应用能力",
                "学习将数据结论转化为行动",
                "提升数据驱动的决策能力"
            ],
            'C6:数据道德': [
                "学习数据隐私保护法规",
                "加强数据伦理意识",
                "遵守数据使用规范"
            ]
        }

        if weakest_dim in suggestions:
            st.write("**建议措施：**")
            for suggestion in suggestions[weakest_dim]:
                st.write(f"• {suggestion}")

    with col2:
        # 显示雷达图
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(projection='polar'))

        # 数据准备
        angles = np.linspace(0, 2 * np.pi, len(rates), endpoint=False).tolist()
        values = rates.copy()

        # 闭合图形
        values.append(values[0])
        angles.append(angles[0])

        # 绘制雷达图
        ax.plot(angles, values, 'o-', linewidth=2)
        ax.fill(angles, values, alpha=0.25)

        # 设置标签
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(C['维度'].tolist())
        ax.set_ylim(0, 100)
        ax.set_title("能力维度雷达图", size=14, pad=20)

        st.pyplot(fig)
        plt.close(fig)


def show_group_portrait():
    """显示群体画像页面 - 优化版"""
    st.header('👥 群体画像分析')

    # 获取所有数据
    df = data_manager.get_all_assessments()

    if df.empty:
        st.info("📊 暂无测评数据，请先完成测评以生成群体画像")
        return

    stats = data_manager.get_assessment_stats()

    # 总体统计
    st.subheader('📈 总体统计')
    col1, col2, col3, col4 = st.columns(4)
    col1.metric('总测评人数', stats.get('total_users', 0))
    col2.metric('总测评次数', stats.get('total_assessments', 0))
    col3.metric('平均综合得分', f"{stats.get('avg_total_score', 0):.2f}")
    col4.metric('近7天测评', stats.get('recent_7days', 0))

    # 1. 各维度得分率分布（双图对比）
    st.subheader('📊 各维度得分率分布')

    # 准备维度得分率数据
    dimension_names = ['C1:数据认知与采集', 'C2:数据处理与分析',
                       'C3:数据存储与验证', 'C4:数据表达与交流',
                       'C5:数据践行', 'C6:数据道德']
    dimension_codes = ['C1', 'C2', 'C3', 'C4', 'C5', 'C6']

    dimension_data = []
    for code, name in zip(dimension_codes, dimension_names):
        rate_col = f'rate_{code}'
        if rate_col in df.columns:
            rates = df[rate_col].dropna().tolist()
            dimension_data.append({
                '维度': name,
                '数据': rates,
                '平均得分率': np.mean(rates) if rates else 0
            })

    if dimension_data:
        col1, col2 = st.columns(2)

        with col1:
            # 左侧：箱线图
            fig, ax = plt.subplots(figsize=(10, 6))
            box_data = [item['数据'] for item in dimension_data]
            labels = [item['维度'] for item in dimension_data]

            bp = ax.boxplot(box_data, labels=labels, patch_artist=True)

            # 设置箱线图颜色
            colors = plt.cm.Set3(np.linspace(0, 1, len(dimension_data)))
            for patch, color in zip(bp['boxes'], colors):
                patch.set_facecolor(color)

            ax.set_ylabel('得分率 (%)', fontsize=12)
            ax.set_title('各维度得分率分布（箱线图）', fontsize=14)
            ax.set_xticklabels(labels, rotation=45, ha='right')
            ax.grid(True, alpha=0.3)

            # 添加平均值点
            for i, data in enumerate(box_data):
                if data:
                    mean_val = np.mean(data)
                    ax.scatter(i + 1, mean_val, color='red', zorder=3, s=50,
                               label='平均值' if i == 0 else '')

            if len(box_data) > 0:
                ax.legend(['平均值'], loc='upper right')

            st.pyplot(fig)
            plt.close(fig)

        with col2:
            # 右侧：小提琴图
            fig, ax = plt.subplots(figsize=(10, 6))

            # 绘制小提琴图
            violin_data = [item['数据'] for item in dimension_data]
            parts = ax.violinplot(violin_data, showmeans=True, showmedians=True)

            # 设置小提琴图颜色
            for pc in parts['bodies']:
                pc.set_facecolor('#1f77b4')
                pc.set_alpha(0.7)
                pc.set_edgecolor('black')

            # 设置其他部分的颜色
            parts['cmeans'].set_color('red')
            parts['cmedians'].set_color('green')

            ax.set_xticks(range(1, len(labels) + 1))
            ax.set_xticklabels(labels, rotation=45, ha='right')
            ax.set_ylabel('得分率 (%)', fontsize=12)
            ax.set_title('各维度得分率密度分布（小提琴图）', fontsize=14)
            ax.grid(True, alpha=0.3)

            # 添加图例
            import matplotlib.patches as mpatches
            red_patch = mpatches.Patch(color='red', label='平均值')
            green_patch = mpatches.Patch(color='green', label='中位数')
            ax.legend(handles=[red_patch, green_patch], loc='upper right')

            st.pyplot(fig)
            plt.close(fig)

    # 2. 专业类别分析
    st.subheader('📊 按专业类别分析')

    if 'major' in df.columns and 'total_score' in df.columns:
        # 获取有数据的专业
        majors_with_data = [m for m in df['major'].dropna().unique()
                            if df[df['major'] == m]['total_score'].count() > 0]

        if len(majors_with_data) > 0:
            # 准备数据
            box_data = []
            box_labels = []

            for major in majors_with_data:
                scores = df[df['major'] == major]['total_score'].dropna().tolist()
                if scores:
                    box_data.append(scores)
                    box_labels.append(major)

            if box_data:
                fig, ax = plt.subplots(figsize=(12, 6))

                # 绘制箱线图
                bp = ax.boxplot(box_data, labels=box_labels, patch_artist=True)

                # 设置颜色
                colors = plt.cm.tab20c(np.linspace(0, 1, len(box_labels)))
                for patch, color in zip(bp['boxes'], colors):
                    patch.set_facecolor(color)

                ax.set_ylabel('综合得分', fontsize=12)
                ax.set_title('各专业类别综合得分分布', fontsize=14)
                ax.set_xticklabels(box_labels, rotation=45, ha='right')
                ax.grid(True, alpha=0.3)

                st.pyplot(fig)
                plt.close(fig)

                # 显示专业统计表格
                st.subheader('专业类别统计摘要')
                major_stats = df.groupby('major')['total_score'].agg([
                    ('人数', 'count'),
                    ('平均分', 'mean'),
                    ('标准差', 'std'),
                    ('最低分', 'min'),
                    ('最高分', 'max')
                ]).round(2).sort_values('平均分', ascending=False)

                st.dataframe(major_stats, use_container_width=True)

    # 3. 年级分析
    st.subheader('📊 按年级分析')

    if 'grade' in df.columns and 'total_score' in df.columns:
        # 定义年级顺序
        grade_order = ['大一', '大二', '大三', '大四', '研究生', '其他']

        # 准备数据
        box_data = []
        box_labels = []

        for grade in grade_order:
            if grade in df['grade'].values:
                scores = df[df['grade'] == grade]['total_score'].dropna().tolist()
                if scores:
                    box_data.append(scores)
                    box_labels.append(grade)

        if box_data:
            fig, ax = plt.subplots(figsize=(10, 6))

            # 绘制箱线图
            bp = ax.boxplot(box_data, labels=box_labels, patch_artist=True)

            # 设置颜色
            colors = plt.cm.Set2(np.linspace(0, 1, len(box_labels)))
            for patch, color in zip(bp['boxes'], colors):
                patch.set_facecolor(color)

            ax.set_ylabel('综合得分', fontsize=12)
            ax.set_title('各年级综合得分分布', fontsize=14)
            ax.grid(True, alpha=0.3)

            st.pyplot(fig)
            plt.close(fig)

            # 显示年级统计表格
            st.subheader('年级统计摘要')
            grade_stats = df.groupby('grade')['total_score'].agg([
                ('人数', 'count'),
                ('平均分', 'mean'),
                ('标准差', 'std'),
                ('最低分', 'min'),
                ('最高分', 'max')
            ]).round(2).reindex(grade_order, fill_value=0)

            st.dataframe(grade_stats, use_container_width=True)

    # 4. 数据经验分析
    st.subheader('📊 按数据经验分析')

    if 'data_exp' in df.columns and 'total_score' in df.columns:
        # 定义经验水平顺序
        exp_order = ['无经验', '少量课程学习', '参加过相关培训',
                     '有项目经验', '专业领域经验丰富']

        # 准备数据
        box_data = []
        box_labels = []

        for exp in exp_order:
            if exp in df['data_exp'].values:
                scores = df[df['data_exp'] == exp]['total_score'].dropna().tolist()
                if scores:
                    box_data.append(scores)
                    box_labels.append(exp)

        if box_data:
            fig, ax = plt.subplots(figsize=(10, 6))

            # 绘制箱线图
            bp = ax.boxplot(box_data, labels=box_labels, patch_artist=True)

            # 设置颜色
            colors = plt.cm.Paired(np.linspace(0, 1, len(box_labels)))
            for patch, color in zip(bp['boxes'], colors):
                patch.set_facecolor(color)

            ax.set_ylabel('综合得分', fontsize=12)
            ax.set_title('不同数据经验水平综合得分分布', fontsize=14)
            ax.set_xticklabels(box_labels, rotation=45, ha='right')
            ax.grid(True, alpha=0.3)

            st.pyplot(fig)
            plt.close(fig)

            # 显示经验统计表格
            st.subheader('数据经验统计摘要')
            exp_stats = df.groupby('data_exp')['total_score'].agg([
                ('人数', 'count'),
                ('平均分', 'mean'),
                ('标准差', 'std'),
                ('最低分', 'min'),
                ('最高分', 'max')
            ]).round(2).reindex(exp_order, fill_value=0)

            st.dataframe(exp_stats, use_container_width=True)

    # 5. 显示当前用户在群体中的位置
    if 'current_result' in st.session_state and st.session_state.get('test_completed', False):
        st.subheader('🎯 您在群体中的位置')

        current_score = st.session_state.current_result['total_score']
        all_scores = [x for x in df['total_score'].dropna().tolist() if isinstance(x, (int, float))]

        if all_scores:
            percentile = np.sum(np.array(all_scores) <= current_score) / len(all_scores) * 100

            col1, col2 = st.columns(2)

            with col1:
                st.metric('您的综合得分', f'{current_score:.2f}')
                st.metric('超过的用户比例', f'{percentile:.1f}%')

                # 计算一些关键统计量
                st.metric('群体平均分', f'{np.mean(all_scores):.2f}')
                st.metric('群体最高分', f'{np.max(all_scores):.2f}')

            with col2:
                # 直方图显示得分分布
                fig, ax = plt.subplots(figsize=(8, 5))

                # 绘制直方图
                ax.hist(all_scores, bins=20, alpha=0.7, color='skyblue',
                        edgecolor='black', density=True)

                # 添加当前用户得分线
                ax.axvline(current_score, color='red', linestyle='--',
                           linewidth=2, label='您的得分')

                # 添加平均线
                ax.axvline(np.mean(all_scores), color='green', linestyle=':',
                           linewidth=2, label='平均得分')

                ax.set_xlabel('综合得分', fontsize=12)
                ax.set_ylabel('密度', fontsize=12)
                ax.set_title('综合得分分布及您的相对位置', fontsize=14)
                ax.legend()
                ax.grid(True, alpha=0.3)

                st.pyplot(fig)
                plt.close(fig)

    # 数据导出
    st.subheader('📥 数据导出')

    if st.button('导出群体数据 (CSV)', use_container_width=True):
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label='点击下载',
            data=csv,
            file_name=f'群体画像数据_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv',
            mime='text/csv',
            key='download_group_data'
        )


def show_system_intro():
    """显示系统介绍"""
    st.header("🏠 系统介绍")

    st.markdown("""
    ## 🌟 系统简介

    本测评系统基于权威的数据素养评估框架，通过六个维度全面评估大学生的数据素养水平：

    1. **C1: 数据认知与采集** - 识别数据需求，掌握数据采集方法
    2. **C2:数据处理与分析** - 清洗、分析数据，提取有价值信息
    3. **C3:数据存储与验证** - 安全存储数据，验证数据质量
    4. **C4:数据表达与交流** - 可视化展示，有效沟通数据成果
    5. **C5:数据践行** - 将数据应用于实际问题解决
    6. **C6:数据道德** - 遵守数据伦理，保护数据隐私

    ## 📋 测评流程

    1. **填写个人信息** - 基本信息有助于更精准的分析
    2. **完成测评题目** - 6个维度共30题，约15-20分钟
    3. **查看个人报告** - 获得详细的分析和建议
    4. **探索群体画像** - 了解自己在群体中的位置

    ## 🔍 功能特色

    - ✅ **科学评估模型** - 基于权威研究构建
    - ✅ **个性化报告** - 针对性的提升建议
    - ✅ **群体对比** - 了解相对水平
    - ✅ **数据可视化** - 直观的图表展示
    - ✅ **数据导出** - 支持结果导出

    ## 📊 适用人群

    - 大学生（各年级、各专业）
    - 教育工作者
    - 数据素养研究者
    - 对数据素养感兴趣的个人

    ## ⚠️ 注意事项

    1. 请根据实际情况如实作答
    2. 测评结果仅供参考，不作为绝对评价
    3. 所有数据将严格保密，仅用于统计分析

    ---

    **开始您的数据素养测评之旅吧！** 🚀
    """)

    # 快速开始按钮
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🚀 立即开始测评", type="primary", use_container_width=True):
            st.session_state.page = "📝 开始测评"
            st.rerun()


def show_admin_page():
    """管理员页面（可选）"""
    st.header('⚙️ 系统管理')

    password = st.text_input("请输入管理员密码", type="password", key="admin_password")

    if password == "admin123":  # 实际应用中应该使用更安全的方式
        st.success("管理员登录成功")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("查看数据库状态", use_container_width=True):
                df = data_manager.get_all_assessments()
                st.write(f"总记录数: {len(df)}")
                if not df.empty:
                    st.dataframe(df.head(), use_container_width=True)

        with col2:
            if st.button("清除所有数据", type="secondary", use_container_width=True):
                if st.checkbox("确认要清除所有数据吗？此操作不可恢复！"):
                    # 这里可以实现清除数据的逻辑
                    st.warning("数据清除功能暂未实现")
    elif password:
        st.warning("密码错误！")


# ----------------- 主程序 -----------------
def main():
    """主函数"""
    # 标题和介绍
    st.title('📊 大学生数据素养测评系统')

    # 初始化session state
    if 'test_completed' not in st.session_state:
        st.session_state.test_completed = False
    if 'answers' not in st.session_state:
        st.session_state.answers = [[] for _ in 题库]
    if 'page' not in st.session_state:
        st.session_state.page = "🏠 系统介绍"

    # 侧边栏导航
    with st.sidebar:
        st.header("导航菜单")

        # 使用radio进行页面导航
        page_options = {
            "🏠 系统介绍": show_system_intro,
            "⚖️ 指标权重": show_weight_page,
            "📝 开始测评": show_test_page,
            "📈 查看结果": show_result_page,
            "👥 群体画像": show_group_portrait,
            "⚙️ 系统管理": show_admin_page
        }

        selected_page = st.radio(
            "选择功能",
            list(page_options.keys()),
            index=list(page_options.keys()).index(st.session_state.page) if st.session_state.page in page_options else 0
        )

        # 更新当前页面
        if selected_page != st.session_state.page:
            st.session_state.page = selected_page
            st.rerun()

        st.divider()

        # 显示系统状态
        if st.session_state.get('test_completed', False):
            st.success("✅ 测评已完成")
            current_result = st.session_state.get('current_result', {})
            if current_result:
                st.metric("您的得分", f"{current_result['total_score']:.2f}")

        st.divider()

        # 系统信息
        st.caption(f"系统版本: 1.0.0")
        st.caption(f"最后更新: 2024年")

    # 显示当前页面
    if st.session_state.page in page_options:
        page_options[st.session_state.page]()
    else:
        show_system_intro()


# 运行主程序
if __name__ == '__main__':
    main()