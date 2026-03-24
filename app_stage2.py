import streamlit as st
import pandas as pd
import openpyxl
import re
import math
from io import BytesIO

class CouponAccountingEngine:
    @staticmethod
    def get_price_map(df):
        """从 All Listing 自动识别原价列"""
        # 常见原价列标题：Price, Your-price, 价格等
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
        return {}, "未找到价格列"

    @staticmethod
    def parse_detailed_errors(error_file, price_map):
        wb = openpyxl.load_workbook(error_file)
        ws = wb.active
        all_results = []

        for row in range(10, ws.max_row + 1):
            # 1. 提取该行所有原始 ASIN
            raw_asins = str(ws.cell(row=row, column=1).value or "")
            if not raw_asins or raw_asins == "None": continue
            row_asins_list = [a.strip() for a in raw_asins.split(';') if a.strip()]

            # 2. 读取 N 列批注
            cell_n = ws.cell(row=row, column=14)
            full_msg = cell_n.comment.text if cell_n.comment else ""
            
            # 3. 将大段批注拆分成 ASIN 独立块
            # 正则：匹配 ASIN 及其后续内容，直到下一个 ASIN 或结尾
            error_blocks = re.findall(r'([A-Z0-9]{10})(.*?)(?=[A-Z0-9]{10}|$)', full_msg, re.DOTALL)
            error_dict = {asin.strip(): msg.strip() for asin, msg in error_blocks}

            for sn in row_asins_list:
                origin_p = price_map.get(sn, 0.0)
                item = {
                    "row": row, "asin": sn, "original_price": origin_p,
                    "target_p": "N/A", "calc_pct": "保持原样", "type": "KEEP",
                    "reason": "正常", "orig_pct": ws.cell(row=row, column=3).value
                }

                if sn in error_dict:
                    msg = error_dict[sn]
                    # 逻辑 A：无参考价
                    if any(x in msg for x in ["没有经验证", "参考价", "历史售价"]):
                        item.update({"type": "REMOVE", "reason": "❌ 无参考价", "calc_pct": "剔除"})
                    
                    # 逻辑 B：力度不足 - 核心提取“要求的净价格”
                    elif "要求的净价格" in msg:
                        # 排除“当前净价格”，精准定位“要求的净价格”后面的数字
                        # 先把文本按行切分，只找包含“要求”的那一行
                        lines = msg.split('\n')
                        req_p = 0.0
                        for line in lines:
                            if "要求的净价格" in line:
                                val_match = re.search(r'[\d\.]+', line)
                                if val_match: req_p = float(val_match.group(0))
                        
                        if origin_p > 0 and req_p > 0:
                            # 计算公式：(Listing原价 - 亚马逊要求价) / Listing原价
                            needed_raw = (origin_p - req_p) / origin_p
                            needed_pct = math.ceil(needed_raw * 100)
                            final_pct = max(5, min(needed_pct, 50))
                            item.update({
                                "type": "ADJUST", "reason": "⚠️ 力度不足", 
                                "target_p": req_p, "calc_pct": f"{final_pct}%",
                                "new_pct_val": final_pct
                            })
                        else:
                            item.update({"type": "ADJUST", "reason": "⚠️ 力度不足(缺原价)", "calc_pct": "需检查"})
                all_results.append(item)
        return all_results

# --- UI 逻辑 ---
st.set_page_config(page_title="Coupon 决策看板", layout="wide")
st.title("🛡️ 阶段 2：报错 ASIN 精准对齐 (财务版)")

if 'user_actions' not in st.session_state:
    st.session_state.user_actions = {}

with st.sidebar:
    st.header("1. 上传文件")
    f_list = st.file_uploader("上传 ALL Listing Report", type=['txt', 'csv'])
    f_err = st.file_uploader("上传报错 Excel", type=['xlsx'])

if f_list and f_err:
    df_l = pd.read_csv(f_list, sep='\t' if f_list.name.endswith('.txt') else ',')
    p_map, p_col = CouponAccountingEngine.get_price_map(df_l)
    items = CouponAccountingEngine.parse_detailed_errors(f_err, p_map)

    # --- 过滤器 ---
    st.subheader("🔍 异常 ASIN 快速处理")
    filter_choice = st.multiselect("显示状态：", ["❌ 无参考价", "⚠️ 力度不足", "正常"], default=["❌ 无参考价", "⚠️ 力度不足"])
    
    filtered_items = [i for i in items if any(s in i['reason'] for s in filter_choice)]

    # --- 决策区域 ---
    for i, it in enumerate(filtered_items):
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([1.5, 1, 1, 1, 2.5])
            c1.markdown(f"**{it['asin']}** (行{it['row']})")
            c2.write(f"原价: €{it['original_price']}")
            c3.write(f"要求价: {it['target_p']}")
            c4.error(it['calc_pct']) if it['type'] != "KEEP" else c4.success(it['calc_pct'])

            # 决策逻辑
            if it['type'] == "REMOVE":
                c5.warning("系统建议：直接剔除（无解）")
                st.session_state.user_actions[it['asin']] = "剔除"
            elif it['type'] == "ADJUST":
                # 让用户判断：如果 15% 太亏了，就选剔除
                user_choice = c5.radio(
                    f"决策：", ["接受修复", "折扣太深，剔除此ASIN"], 
                    key=f"act_{i}", horizontal=True
                )
                st.session_state.user_actions[it['asin']] = user_choice
            else:
                c5.write("✅ 正常，已自动保留")
                st.session_state.user_actions[it['asin']] = "保留"

    # --- 最终导出 ---
    st.divider()
    if st.button("🚀 生成最终提报序列 (排除剔除项，合并修复项)", type="primary"):
        final_groups = {}
        for it in items:
            asin = it['asin']
            # 获取用户决策（默认为保留）
            action = st.session_state.user_actions.get(asin, "保留")
            
            if action in ["保留", "接受修复"]:
                # 确定最终使用的百分比
                pct = it.get('new_pct_val', it.get('orig_pct', 5))
                if pct not in final_groups: final_groups[pct] = []
                final_groups[pct].append(asin)
        
        for pct, asins in final_groups.items():
            with st.status(f"📦 折扣 {pct}% 的 ASIN 序列", expanded=True):
                st.code(";".join(asins))
