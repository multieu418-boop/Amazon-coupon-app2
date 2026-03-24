import streamlit as st
import pandas as pd
import openpyxl
import re
from io import BytesIO
from copy import copy

class CouponRefactor:
    @staticmethod
    def calculate_needed_discount(current_p, target_p):
        """核心算法：计算达标折扣并向上取整（确保过审）"""
        if current_p <= 0 or target_p <= 0: return 0
        # 计算公式：(原价 - 目标净价) / 原价
        raw_discount = (current_p - target_p) / current_p
        # 转为百分比并向上取整 (例如 12.1% -> 13%)
        import math
        needed_pct = math.ceil(raw_discount * 100)
        # 亚马逊 Coupon 最低 5%，最高 50%
        return max(5, min(needed_pct, 50))

    @staticmethod
    def parse_errors(error_file, listing_df):
        wb = openpyxl.load_workbook(error_file)
        ws = wb.active
        # 建立价格字典
        asin_col = next((c for c in listing_df.columns if 'asin' in c.lower()), listing_df.columns[0])
        price_col = next((c for c in listing_df.columns if 'price' in c.lower()), listing_df.columns[1])
        price_map = pd.Series(listing_df[price_col].values, index=listing_df[asin_col]).to_dict()

        error_items = []
        for row in range(10, ws.max_row + 1):
            cell = ws.cell(row=row, column=14) # N列报错
            if cell.comment:
                msg = cell.comment.text
                # 提取 ASIN
                asin_match = re.search(r'[A-Z0-9]{10}', msg)
                asin = asin_match.group(0) if asin_match else "Unknown"
                curr_p = price_map.get(asin, 0)
                
                # 类型 A：无参考价
                if any(x in msg for x in ["没有经验证", "参考价", "历史售价"]):
                    error_items.append({"asin": asin, "type": "REMOVE", "reason": "无参考价", "curr_p": curr_p, "suggested": "剔除"})
                
                # 类型 B：折扣力度不足
                elif any(x in msg for x in ["要求", "净价格", "提高"]):
                    target_match = re.search(r'(?:价格|price)：?\s*[€\$]?([\d\.]+)', msg)
                    target_p = float(target_match.group(1)) if target_match else 0
                    needed = CouponRefactor.calculate_needed_discount(curr_p, target_p)
                    error_items.append({"asin": asin, "type": "ADJUST", "reason": f"限价{target_p}", "curr_p": curr_p, "target_p": target_p, "suggested": needed})
        return error_items

# --- UI 界面 ---
st.set_page_config(page_title="Coupon 报错决策看板", layout="wide")
st.title("⚖️ Coupon 报错决策与自动合并系统")

col1, col2 = st.columns(2)
with col1:
    list_file = st.file_uploader("1. 上传 ALL Listing (获取最新Price)", type=['txt', 'csv'])
with col2:
    err_file = st.file_uploader("2. 上传亚马逊报错 Excel", type=['xlsx'])

if list_file and err_file:
    df_list = pd.read_csv(list_file, sep='\t' if list_file.name.endswith('.txt') else ',')
    items = CouponRefactor.parse_errors(err_file, df_list)
    
    st.subheader("📊 报错 ASIN 详细列表与计算结果")
    
    decision_results = []
    
    # 建立表头
    cols = st.columns([1, 2, 1, 1, 1, 2])
    cols[0].write("**ASIN**")
    cols[1].write("**报错原因**")
    cols[2].write("**当前价**")
    cols[3].write("**建议操作**")
    cols[4].write("**计算结果**")
    cols[5].write("**最终决策**")

    for i, item in enumerate(items):
        with st.container():
            r = st.columns([1, 2, 1, 1, 1, 2])
            r[0].write(item['asin'])
            r[1].write(item['reason'])
            r[2].write(f"{item['curr_p']}")
            
            if item['type'] == "REMOVE":
                r[3].error("建议剔除")
                r[4].write("-")
                choice = r[5].selectbox("决策", ["确认剔除", "强制保留(不推荐)"], key=f"choice_{i}")
                if choice == "确认剔除":
                    decision_results.append({"asin": item['asin'], "action": "REMOVE"})
            else:
                r[3].warning("建议增加力度")
                r[4].write(f"{item['suggested']}%")
                choice = r[5].radio("决策", ["按建议力度提报", "剔除此 ASIN"], key=f"choice_{i}", horizontal=True)
                if choice == "按建议力度提报":
                    decision_results.append({"asin": item['asin'], "action": "ADJUST", "discount": item['suggested']})
                else:
                    decision_results.append({"asin": item['asin'], "action": "REMOVE"})
        st.divider()

    if st.button("🏗️ 开始智能合并并生成新 Coupon 提报单", type="primary"):
        # --- 核心归纳逻辑 ---
        to_remove = [d['asin'] for d in decision_results if d['action'] == "REMOVE"]
        to_adjust = [d for d in decision_results if d['action'] == "ADJUST"]
        
        # 按折扣力度分组
        groups = {}
        for entry in to_adjust:
            d_val = entry['discount']
            if d_val not in groups: groups[d_val] = []
            groups[d_val].append(entry['asin'])
        
        st.success(f"✅ 处理完成！已剔除 {len(to_remove)} 个无效 ASIN。")
        
        # 显示合并后的结果
        for dist, asins in groups.items():
            with st.status(f"📦 生成新 Coupon：力度 {dist}%", expanded=True):
                st.write(f"包含 ASIN ({len(asins)}个):")
                st.code(";".join(asins))
                st.write("您可以直接将此 ASIN 序列复制到阶段 1 的工具中提报。")
