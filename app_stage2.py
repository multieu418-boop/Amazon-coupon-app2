import streamlit as st
import pandas as pd
import openpyxl
import re
import math
import chardet

# 1. 自动识别价格列和ASIN列
def get_clean_map(df):
    p_keywords = ['price', 'your-price', '价格', 'retail-price']
    a_keywords = ['asin', 'sku-asin', '商品编码']
    t_price, t_asin = None, None
    for col in df.columns:
        c_low = str(col).lower()
        if any(k in c_low for k in p_keywords) and t_price is None: t_price = col
        if any(k in c_low for k in a_keywords) and t_asin is None: t_asin = col
    if t_asin and t_price:
        df[t_asin] = df[t_asin].astype(str).str.strip().str.upper()
        df[t_price] = pd.to_numeric(df[t_price], errors='coerce').fillna(0.0)
        return df.set_index(t_asin)[t_price].to_dict(), t_price
    return {}, None

# 2. 核心 UI
st.set_page_config(page_title="Coupon 决策看板", layout="wide")
st.title("🛡️ 阶段 2：报错 ASIN 财务对齐与盈亏决策")

# 用于存储用户的勾选决策
if 'user_decisions' not in st.session_state:
    st.session_state.user_decisions = {}

with st.sidebar:
    list_f = st.file_uploader("1. 上传 ALL Listing (处理乱码版)", type=['txt', 'csv'])
    err_f = st.file_uploader("2. 上传报错 Excel", type=['xlsx'])

if list_f and err_f:
    # --- 解决乱码的读取方式 ---
    raw = list_f.read(10000)
    enc = chardet.detect(raw)['encoding']
    list_f.seek(0)
    df_l = pd.read_csv(list_f, sep='\t' if list_f.name.endswith('.txt') else ',', encoding=enc if enc else 'gbk')
    
    p_map, p_col = get_clean_map(df_l)
    
    # 解析 Excel (此处调用之前的 parse 逻辑，重点抓取“要求的净价格”)
    # ... (假设已经解析出 items 列表)

    # --- 增加筛选功能 ---
    st.subheader("🔍 异常排查筛选")
    status_filter = st.multiselect(
        "只看这些状态的 ASIN：",
        ["❌ 无参考价", "⚠️ 力度不足", "✅ 正常"],
        default=["❌ 无参考价", "⚠️ 力度不足"]
    )

    # --- 交互决策列表 ---
    for i, it in enumerate(items):
        if it['reason'] not in status_filter: continue
        
        with st.container(border=True):
            col_info, col_calc, col_action = st.columns([2, 2, 2])
            
            with col_info:
                st.markdown(f"**ASIN: {it['asin']}**")
                st.caption(f"原始提报行：{it['row']}")
            
            with col_calc:
                if it['type'] == "ADJUST":
                    st.write(f"原价: **€{it['original_price']}**")
                    st.write(f"亚马逊要求净价: <span style='color:red'>**€{it['target_p']}**</span>", unsafe_allow_html=True)
                    st.write(f"建议力度: **{it['calc_pct']}**")
                else:
                    st.write(it['reason'])

            with col_action:
                if it['type'] == "ADJUST":
                    # 核心：盈亏判断按钮
                    choice = st.radio(
                        "运营决策：",
                        ["接受修复 (增加力度)", "力度太大，剔除此 ASIN"],
                        key=f"choice_{it['asin']}_{i}",
                        horizontal=True
                    )
                    st.session_state.user_decisions[it['asin']] = choice
                elif it['type'] == "REMOVE":
                    st.warning("此 ASIN 无参考价，系统建议直接剔除")
                    st.session_state.user_decisions[it['asin']] = "剔除"

    # --- 最终导出逻辑 ---
    st.divider()
    if st.button("🚀 生成最终提报序列 (基于我的决策)", type="primary"):
        # 逻辑：合并所有“接受修复”和“原本正常”的 ASIN
        # ... (按百分比归类代码)
        st.success("处理完成！请在下方展开查看新提报组。")
