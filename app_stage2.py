import streamlit as st
import pandas as pd
import openpyxl
import re
import math
from io import BytesIO

# --- 核心解析逻辑 (保持鲁棒性) ---
class CouponDecisionEngine:
    @staticmethod
    def get_price_map(df):
        price_keywords = ['price', 'your-price', '价格', 'amount']
        asin_keywords = ['asin', 'sku-asin', '商品编码']
        t_price, t_asin = None, None
        for col in df.columns:
            c_low = str(col).lower()
            if any(k in c_low for k in price_keywords) and t_price is None: t_price = col
            if any(k in c_low for k in asin_keywords) and t_asin is None: t_asin = col
        if t_asin and t_price:
            df[t_asin] = df[t_asin].astype(str).str.strip().str.upper()
            df[t_price] = pd.to_numeric(df[t_price], errors='coerce').fillna(0.0)
            return df.set_index(t_asin)[t_price].to_dict(), t_price
        return {}, "未找到价格"

# --- UI 界面 ---
st.set_page_config(page_title="Coupon 运营决策台", layout="wide")
st.title("⚖️ Coupon 报错：深度折扣决策中心")

# 初始化 Session State 用于存储用户的手动决策
if 'user_decisions' not in st.session_state:
    st.session_state.user_decisions = {}

with st.sidebar:
    list_file = st.file_uploader("1. 上传 ALL Listing", type=['txt', 'csv'])
    err_file = st.file_uploader("2. 上传亚马逊报错文件", type=['xlsx'])

if list_file and err_file:
    df_l = pd.read_csv(list_file, sep='\t' if list_file.name.endswith('.txt') else ',')
    p_map, _ = CouponDecisionEngine.get_price_map(df_l)
    
    # 模拟解析逻辑 (这里使用之前定义的解析函数)
    # 假设 items 是解析出来的列表
    items = [] # 此处应调用之前的 parse_error_comments 函数获取全量数据

    # --- 筛选器 ---
    st.subheader("🔍 报错处理看板")
    view_mode = st.radio("查看范围：", ["仅查看需增加力度的", "查看全部报错", "查看正常保留的"], horizontal=True)

    # 过滤逻辑 (示例)
    # ... 

    # --- 交互决策列表 ---
    for i, it in enumerate(items):
        # 针对“力度不足”的 ASIN 提供特殊的决策 UI
        if it['type'] == "ADJUST":
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
                c1.write(f"**{it['asin']}**")
                c2.write(f"原价: €{it['original_price']}")
                c3.error(f"需增加至: {it['calc_discount']}")
                
                # 用户手动判断：是修复还是剔除
                decision = c4.radio(
                    f"决策 (行 {it['row']}):",
                    ["接受建议力度", "太亏了，直接剔除"],
                    key=f"dec_{i}",
                    horizontal=True
                )
                # 存入 Session 供最后缝合使用
                st.session_state.user_decisions[it['asin']] = decision

        elif it['type'] == "REMOVE":
            st.error(f"ASIN: {it['asin']} - 无参考价，系统已自动标记为剔除。")

    # --- 最终缝合 ---
    st.divider()
    if st.button("🚀 按照我的决策：生成最终提报序列", type="primary"):
        final_list = {}
        for it in items:
            asin = it['asin']
            # 如果是正常保留的
            if it['type'] == "KEEP":
                pct = it['orig_data']['orig_discount']
                if pct not in final_list: final_list[pct] = []
                final_list[pct].append(asin)
            
            # 如果是力度不足的，看用户的决策
            elif it['type'] == "ADJUST":
                user_choice = st.session_state.user_decisions.get(asin)
                if user_choice == "接受建议力度":
                    pct = it['new_pct_val']
                    if pct not in final_list: final_list[pct] = []
                    final_list[pct].append(asin)
                # 如果用户选了“太亏了”，则不加入任何 final_list
        
        # 输出结果
        for p, a_list in final_list.items():
            st.success(f"新提报组 ({p}%):")
            st.code(";".join(a_list))
