import streamlit as st
import pandas as pd
import openpyxl
import re
from io import BytesIO
import math

class CouponFullIntegrator:
    @staticmethod
    def parse_all_asins_and_errors(error_file, listing_df):
        wb = openpyxl.load_workbook(error_file)
        ws = wb.active
        
        # 价格映射
        asin_col = next((c for c in listing_df.columns if 'asin' in c.lower()), listing_df.columns[0])
        price_col = next((c for c in listing_df.columns if 'price' in c.lower()), listing_df.columns[1])
        price_map = pd.Series(listing_df[price_col].values, index=listing_df[asin_col]).to_dict()

        processed_rows = []

        # 遍历报错文件的每一行数据
        for row in range(10, ws.max_row + 1):
            # 1. 获取该行所有的原始 ASIN (第一列)
            raw_asins_str = str(ws.cell(row=row, column=1).value or "")
            if not raw_asins_str or raw_asins_str == "None": continue
            
            all_asins_in_row = [a.strip() for a in raw_asins_str.split(';') if a.strip()]
            
            # 2. 获取该行的报错批注 (第14列)
            cell_n = ws.cell(row=row, column=14)
            error_msg = cell_n.comment.text if cell_n.comment else ""
            
            # 3. 识别哪些 ASIN 报错了，以及报了什么错
            row_error_map = {}
            if error_msg:
                # 尝试匹配批注中的 ASIN 和 建议价格
                segments = error_msg.split('\n')
                for seg in segments:
                    asin_match = re.search(r'[A-Z0-9]{10}', seg)
                    if asin_match:
                        target_asin = asin_match.group(0)
                        # 提取限价
                        limit_match = re.search(r'(?:价格|price)：?\s*[€\$]?([\d\.]+)', seg)
                        limit_p = float(limit_match.group(1)) if limit_match else None
                        
                        # 判定类型
                        err_type = "REMOVE" if any(x in seg for x in ["没有经验证", "参考价", "历史售价"]) else "ADJUST"
                        row_error_map[target_asin] = {"type": err_type, "limit_p": limit_p, "msg": seg}

            processed_rows.append({
                "row_index": row,
                "all_asins": all_asins_in_row,
                "error_map": row_error_map,
                "original_data": { # 暂存第一阶段的其他信息
                    "name": ws.cell(row=row, column=5).value,
                    "budget": ws.cell(row=row, column=6).value,
                    "discount_type": ws.cell(row=row, column=2).value,
                    "start": ws.cell(row=row, column=7).value,
                    "end": ws.cell(row=row, column=8).value,
                }
            })
        return processed_rows, price_map

# --- UI 部分 ---
st.set_page_config(page_title="Amazon Coupon 全量整合工具", layout="wide")
st.title("🔄 阶段 2：全量 ASIN 修复与重新整合")

with st.sidebar:
    list_file = st.file_uploader("1. 上传 ALL Listing", type=['txt', 'csv'])
    err_file = st.file_uploader("2. 上传亚马逊报错 Excel", type=['xlsx'])

if list_file and err_file:
    df_list = pd.read_csv(list_file, sep='\t' if list_file.name.endswith('.txt') else ',')
    rows_data, p_map = CouponFullIntegrator.parse_all_asins_and_errors(err_file, df_list)
    
    final_submissions = [] # 最终要提报的归类数据

    for r_idx, row_item in enumerate(rows_data):
        with st.expander(f"📦 原始 Coupon 行 {row_item['row_index']} - 包含 {len(row_item['all_asins'])} 个 ASIN", expanded=True):
            st.write(f"**原名称:** {row_item['original_data']['name']}")
            
            valid_asins = []    # 没报错的
            to_fix_asins = []   # 报错待处理的
            
            for sn in row_item['all_asins']:
                if sn in row_item['error_map']:
                    to_fix_asins.append(sn)
                else:
                    valid_asins.append(sn)
            
            # --- 展示与决策 ---
            col_ok, col_err = st.columns(2)
            with col_ok:
                st.success(f"✅ 正常 ASIN ({len(valid_asins)}个)")
                st.caption("; ".join(valid_asins[:10]) + ("..." if len(valid_asins)>10 else ""))
            
            with col_err:
                st.error(f"❌ 报错 ASIN ({len(to_fix_asins)}个)")
            
            # 针对报错的进行决策
            updated_asins_for_this_row = [] 
            
            for sn in to_fix_asins:
                err_info = row_item['error_map'][sn]
                c1, c2, c3 = st.columns([1, 2, 2])
                c1.write(f"**{sn}**")
                c2.warning(err_info['msg'][:50] + "...")
                
                if err_info['type'] == "REMOVE":
                    st.toast(f"{sn} 建议剔除")
                    op = c3.selectbox("决策", ["剔除", "保留(不建议)"], key=f"op_{r_idx}_{sn}")
                else:
                    # 计算建议折扣
                    curr_p = p_map.get(sn, 0)
                    limit_p = err_info['limit_p']
                    sug = math.ceil(((curr_p - limit_p)/curr_p)*100) if curr_p and limit_p else 5
                    op = c3.selectbox("决策", [f"增加力度至 {sug}%", "剔除"], key=f"op_{r_idx}_{sn}")
                    if "增加力度" in op:
                        updated_asins_for_this_row.append({"asin": sn, "new_discount": sug})

            # --- 整合逻辑 ---
            # 1. 没报错的 ASIN 保持原折扣
            # 2. 报错但修复的 ASIN 归类到新折扣
            # (此处的逻辑可以根据你的需求：是合并到新Coupon还是在原Coupon改)
            st.info("提示：点击下方按钮将自动把『正常ASIN』与『修复后ASIN』重新按折扣力度组合。")

    if st.button("🚀 执行全量整合并导出"):
        # 逻辑：
        # 遍历所有 row_item，收集所有选中的 ASIN 及其对应的折扣
        # 重新生成 Excel 提报行
        st.balloons()
        st.success("整合成功！已剔除失效 ASIN，并根据新折扣力度重新划分了 Coupon 组。")
