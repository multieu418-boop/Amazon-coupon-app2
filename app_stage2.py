import streamlit as st
import pandas as pd
import openpyxl
import re
from io import BytesIO
from copy import copy

# --- 核心解析函数 ---
def parse_amazon_error_comments(error_file, listing_df):
    """精准提取亚马逊批注中的 ASIN 和错误限制"""
    wb = openpyxl.load_workbook(error_file)
    ws = wb.active
    
    # 建立价格映射
    price_map = {}
    if listing_df is not None:
        # 尝试匹配常见的 Listing 报告列名
        asin_col = next((c for c in listing_df.columns if 'asin' in c.lower()), listing_df.columns[0])
        price_col = next((c for c in listing_df.columns if 'price' in c.lower()), listing_df.columns[1])
        price_map = pd.Series(listing_df[price_col].values, index=listing_df[asin_col]).to_dict()

    error_list = []
    # 亚马逊报错通常在 N 列 (第14列)，从第10行开始
    for row in range(10, ws.max_row + 1):
        result_cell = ws.cell(row=row, column=14)
        if result_cell.comment:
            msg = result_cell.comment.text
            # 提取限制价格 (如: lower than 15.99)
            limit_match = re.search(r'(?:lower than|低于)\s*([\d\.]+)', msg)
            limit_val = float(limit_match.group(1)) if limit_match else None
            
            # 获取该行的原始 ASIN 数据
            raw_asin_str = str(ws.cell(row=row, column=1).value or "")
            
            error_list.append({
                "row": row,
                "error_msg": msg,
                "original_asins": raw_asin_str,
                "limit_price": limit_val
            })
    return error_list, price_map, wb

# --- UI 界面 ---
st.set_page_config(page_title="Amazon 报错修复工具", layout="wide")
st.title("🔴 阶段 2：Coupon 报错一键修复")

col_file1, col_file2 = st.columns(2)
with col_file1:
    all_listing = st.file_uploader("1. 上传 ALL Listing Report", type=['txt', 'csv'])
with col_file2:
    error_report = st.file_uploader("2. 上传亚马逊返回的【报错文件】", type=['xlsx'])

if all_listing and error_report:
    # 加载 Listing 数据
    sep = '\t' if all_listing.name.endswith('.txt') else ','
    df_listing = pd.read_csv(all_listing, sep=sep)
    
    errors, p_map, workbook = parse_amazon_error_comments(error_report, df_listing)
    
    if not errors:
        st.warning("⚠️ 未在 N 列探测到报错批注，请确认文件是否正确。")
    else:
        st.success(f"✅ 成功解析到 {len(errors)} 处报错！")
        
        # 准备修复后的工作表
        ws = workbook.active
        
        for i, item in enumerate(errors):
            with st.expander(f"报错行：{item['row']} | 内容预览", expanded=True):
                st.error(f"亚马逊原始报错：{item['error_msg']}")
                
                # 智能计算
                asins = item['original_asins'].split(';')
                ref_asin = asins[0] if asins else "Unknown"
                current_p = p_map.get(ref_asin, 0)
                
                c1, c2 = st.columns(2)
                with c1:
                    action = st.radio(f"处理方案 (行 {item['row']})", ["保留并修改折扣", "彻底剔除该行"], key=f"act_{i}")
                
                with c2:
                    if item['limit_price'] and current_p > 0:
                        suggested = int(((current_p - item['limit_price']) / current_p) * 100)
                        st.info(f"ASIN: {ref_asin} | 当前价: {current_p} \n\n 建议最大折扣: **{suggested}%**")
                        new_val = st.text_input("修正后的折扣数值 (仅数字)", value=str(suggested), key=f"val_{i}")
                    else:
                        new_val = st.text_input("修正后的折扣数值 (手动输入)", key=f"val_{i}")

                # 实时更新逻辑 (仅演示，点击下载时统一执行)
                if action == "彻底剔除该行":
                    for col in range(1, ws.max_column + 1):
                        ws.cell(row=item['row'], column=col).value = None
                else:
                    # 假设折扣数值在第3列 (根据你的模板修改)
                    ws.cell(row=item['row'], column=3).value = new_val

        st.divider()
        if st.button("💾 生成修复后的提报文件", type="primary"):
            output = BytesIO()
            workbook.save(output)
            st.download_button("📥 点击下载修复版 Excel", data=output.getvalue(), file_name="Fixed_Coupon_Report.xlsx")
            st.balloons()