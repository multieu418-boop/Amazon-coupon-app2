import streamlit as st
import pandas as pd
import openpyxl
import re
from io import BytesIO

class CouponRepairEngine:
    @staticmethod
    def parse_errors(error_file, listing_df):
        wb = openpyxl.load_workbook(error_file)
        ws = wb.active
        
        # 建立 All Listing 价格映射
        price_map = {}
        if listing_df is not None:
            # 自动识别列名：假设包含 'asin' 和 'price' 字样
            asin_col = next((c for c in listing_df.columns if 'asin' in c.lower()), listing_df.columns[0])
            price_col = next((c for c in listing_df.columns if 'price' in c.lower()), listing_df.columns[1])
            price_map = pd.Series(listing_df[price_col].values, index=listing_df[asin_col]).to_dict()

        parsed_data = []
        # 扫描 N 列 (第14列) 的报错批注
        for row in range(10, ws.max_row + 1):
            cell = ws.cell(row=row, column=14)
            if cell.comment:
                msg = cell.comment.text
                # 1. 提取报错里的 ASIN (通常在批注开头)
                asin_match = re.search(r'[A-Z0-9]{10}', msg)
                error_asin = asin_match.group(0) if asin_match else "未知ASIN"
                
                # 2. 获取当前 Listing 里的实时价格
                current_price = price_map.get(error_asin, 0)
                
                # 3. 错误分类与计算逻辑
                category = "其他错误"
                suggestion = ""
                action_type = "MANUAL" # 手动处理

                # 类型 A：参考价缺失 (No Valid Reference Price)
                if "没有经验证" in msg or "参考价" in msg:
                    category = "❌ 参考价缺失 (需剔除)"
                    suggestion = f"该 ASIN {error_asin} 无历史售价记录，亚马逊无法验证折扣，建议直接剔除。"
                    action_type = "REMOVE"

                # 类型 B：折扣力度不足 (Price Threshold)
                elif "要求的净价格" in msg or "提高优惠券折扣" in msg:
                    category = "⚠️ 折扣力度不足"
                    # 正则提取要求的净价格 (例: 40.84)
                    req_match = re.search(r'(?:要求的净价格|Required net price)：?\s*[€\$]?([\d\.]+)', msg)
                    if req_match and current_price > 0:
                        required_net = float(req_match.group(1))
                        # 计算需要设置的折扣百分比: (当前价 - 要求净价) / 当前价
                        needed_discount_pct = round(((current_price - required_net) / current_price) * 100, 2)
                        suggestion = f"当前价: {current_price} | 亚马逊要求净价: {required_net} \n\n 👉 需设置折扣至少为: **{needed_discount_pct}%**"
                        action_type = "ADJUST"
                    else:
                        suggestion = "未能识别具体金额，请根据报错手动调整折扣。"

                parsed_data.append({
                    "row": row,
                    "asin": error_asin,
                    "category": category,
                    "msg": msg,
                    "current_price": current_price,
                    "suggestion": suggestion,
                    "action_type": action_type
                })
        return parsed_data, wb

# --- UI 界面 ---
st.set_page_config(page_title="Coupon 智能修复助手", layout="wide")
st.title("🛠️ 阶段 2：报错智能分类与计算")

with st.sidebar:
    st.header("上传数据")
    listing_file = st.file_uploader("1. 上传 ALL Listing (获取最新Price)", type=['txt', 'csv'])
    error_file = st.file_uploader("2. 上传亚马逊报错 Excel", type=['xlsx'])

if listing_file and error_file:
    # 加载 Listing
    sep = '\t' if listing_file.name.endswith('.txt') else ','
    df_listing = pd.read_csv(listing_file, sep=sep)
    
    results, workbook = CouponRepairEngine.parse_errors(error_file, df_listing)
    
    if not results:
        st.warning("未能解析到有效报错批注。")
    else:
        st.success(f"解析完成！共发现 {len(results)} 个问题 ASIN。")
        
        for i, item in enumerate(results):
            with st.container(border=True):
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.markdown(f"**行号：{item['row']} | ASIN: {item['asin']}**")
                    st.info(item['category'])
                with c2:
                    st.write(f"**原始报错内容：** {item['msg']}")
                    st.success(f"**处理建议：** {item['suggestion']}")
                
                # 操作区
                if item['action_type'] == "REMOVE":
                    if st.button(f"确认从第 {item['row']} 行剔除此 ASIN", key=f"btn_{i}"):
                        st.toast("已记录剔除操作")
                elif item['action_type'] == "ADJUST":
                    new_val = st.number_input(f"调整第 {item['row']} 行的折扣数值", value=0.0, key=f"inp_{i}")
                    if st.button(f"应用此折扣", key=f"btn_{i}"):
                        st.toast("已更新折扣数值")

        st.divider()
        if st.button("💾 生成修复后的提报文件", type="primary"):
            # 此处执行 openpyxl 的修改逻辑
            st.write("正在构建最终文件...")
