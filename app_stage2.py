import streamlit as st
import pandas as pd
import openpyxl
import re
import math
import chardet

# --- 逻辑层：数据处理 ---
class CouponAccountingMaster:
    @staticmethod
    def read_file_with_encoding(file):
        """处理亚马逊 TXT 文件的乱码问题"""
        raw_data = file.read()
        result = chardet.detect(raw_data)
        encoding = result['encoding'] if result['encoding'] else 'gbk'
        file.seek(0)
        # 兼容 Tab 分隔的 TXT 和逗号分隔的 CSV
        sep = '\t' if file.name.endswith('.txt') else ','
        try:
            return pd.read_csv(file, sep=sep, encoding=encoding)
        except:
            file.seek(0)
            return pd.read_csv(file, sep=sep, encoding='gbk')

    @staticmethod
    def get_price_map(df):
        """识别原价列"""
        p_keys = ['price', 'your-price', '价格', 'retail-price']
        a_keys = ['asin', 'sku-asin', '商品编码']
        t_p, t_a = None, None
        for col in df.columns:
            c = str(col).lower()
            if any(k in c for k in p_keys) and t_p is None: t_p = col
            if any(k in c for k in a_keys) and t_a is None: t_a = col
        if t_a and t_p:
            df[t_a] = df[t_a].astype(str).str.strip().str.upper()
            df[t_p] = pd.to_numeric(df[t_p], errors='coerce').fillna(0.0)
            return df.set_index(t_a)[t_p].to_dict(), t_p
        return {}, None

    @staticmethod
    def parse_errors(error_file, price_map):
        """解析报错批注，精准提取'要求的净价格'"""
        wb = openpyxl.load_workbook(error_file)
        ws = wb.active
        parsed = []
        for row in range(10, ws.max_row + 1):
            raw_asins = str(ws.cell(row=row, column=1).value or "")
            if not raw_asins or raw_asins == "None": continue
            asins_in_row = [a.strip() for a in raw_asins.split(';') if a.strip()]
            
            # 获取 N 列批注
            cell_n = ws.cell(row=row, column=14)
            msg = cell_n.comment.text if cell_n.comment else ""
            
            # 拆分报错块
            error_dict = {a.strip(): m.strip() for a, m in re.findall(r'([A-Z0-9]{10})(.*?)(?=[A-Z0-9]{10}|$)', msg, re.DOTALL)}

            for sn in asins_in_row:
                origin_p = price_map.get(sn, 0.0)
                item = {
                    "row": row, "asin": sn, "origin_p": origin_p, "target_p": "N/A",
                    "type": "KEEP", "status": "✅ 正常 (保留)", "suggested_pct": "原样",
                    "orig_pct": ws.cell(row=row, column=3).value
                }
                if sn in error_dict:
                    txt = error_dict[sn]
                    if any(x in txt for x in ["没有经验证", "参考价"]):
                        item.update({"type": "REMOVE", "status": "❌ 无参考价 (剔除)", "suggested_pct": "剔除"})
                    elif "要求的净价格" in txt:
                        # 精准提取“要求的净价格”后面的数值，忽略“当前净价格”
                        req_p_match = re.search(r'要求的净价格：?\s*[€\$]?\s*([\d\.]+)', txt)
                        req_p = float(req_p_match.group(1)) if req_p_match else 0.0
                        if origin_p > 0 and req_p > 0:
                            needed = math.ceil(((origin_p - req_p) / origin_p) * 100)
                            final_pct = max(5, min(needed, 50))
                            item.update({
                                "type": "ADJUST", "status": "⚠️ 力度不足", 
                                "target_p": req_p, "suggested_pct": f"{final_pct}%",
                                "new_pct": final_pct
                            })
                parsed.append(item)
        return parsed

# --- UI 层 ---
st.set_page_config(page_title="Amazon Coupon 修复大师", layout="wide")
st.title("🛡️ 阶段 2：全量修复与盈亏决策看板")

if 'decisions' not in st.session_state:
    st.session_state.decisions = {}

with st.sidebar:
    st.header("1. 上传文件")
    f_list = st.file_uploader("上传 ALL Listing Report", type=['txt', 'csv'])
    f_err = st.file_uploader("上传报错 Excel", type=['xlsx'])

if f_list and f_err:
    df_l = CouponAccountingMaster.read_file_with_encoding(f_list)
    p_map, p_col = CouponAccountingMaster.get_price_map(df_l)
    items = CouponAccountingMaster.parse_errors(f_err, p_map)

    # 筛选功能
    st.subheader("🔍 异常处理队列")
    filters = st.multiselect("查看类型：", ["❌ 无参考价 (剔除)", "⚠️ 力度不足", "✅ 正常 (保留)"], default=["❌ 无参考价 (剔除)", "⚠️ 力度不足"])
    
    to_show = [i for i in items if i['status'] in filters]

    for i, it in enumerate(to_show):
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([1.5, 2, 1, 2.5])
            c1.markdown(f"**{it['asin']}**")
            
            if it['type'] == "ADJUST":
                c2.write(f"原价: €{it['origin_p']} | 要求净价: **€{it['target_p']}**")
                c3.error(f"需: {it['suggested_pct']}")
                choice = c4.radio("决策", ["接受修复", "折扣太深，剔除"], key=f"d_{it['asin']}_{i}", horizontal=True)
                st.session_state.decisions[it['asin']] = choice
            elif it['type'] == "REMOVE":
                c2.write("原因：亚马逊无法验证参考价")
                c3.warning("剔除")
                st.session_state.decisions[it['asin']] = "剔除"
            else:
                c2.write("状态正常")
                c3.success("保留")
                st.session_state.decisions[it['asin']] = "保留"

    st.divider()
    if st.button("🚀 生成最终提报序列", type="primary"):
        final_groups = {}
        for it in items:
            decision = st.session_state.decisions.get(it['asin'], "保留")
            if decision in ["保留", "接受修复"]:
                pct = it.get('new_pct', it.get('orig_pct', 5))
                if pct not in final_groups: final_groups[pct] = []
                final_groups[pct].append(it['asin'])
        
        for pct, asins in final_groups.items():
            with st.expander(f"📦 提报组 - {pct}% 折扣"):
                st.code(";".join(asins))
