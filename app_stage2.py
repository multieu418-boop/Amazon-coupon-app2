import streamlit as st
import pandas as pd
import openpyxl
import re
import math
from io import BytesIO

class CouponAccountingIntegrator:
    @staticmethod
    def get_price_map(df):
        """自动适配 All Listing 的价格列名"""
        price_keywords = ['price', 'your-price', '价格', 'amount', 'retail-price']
        asin_keywords = ['asin', 'sku-asin', '商品编码']
        target_price_col, target_asin_col = None, None
        
        for col in df.columns:
            col_lower = str(col).lower()
            if any(k in col_lower for k in price_keywords) and target_price_col is None:
                target_price_col = col
            if any(k in col_lower for k in asin_keywords) and target_asin_col is None:
                target_asin_col = col
        
        if target_asin_col and target_price_col:
            df[target_asin_col] = df[target_asin_col].astype(str).str.strip().str.upper()
            # 转换价格为浮点数，防止计算报错
            df[target_price_col] = pd.to_numeric(df[target_price_col], errors='coerce').fillna(0.0)
            return df.set_index(target_asin_col)[target_price_col].to_dict(), target_price_col
        return {}, "未找到价格列"

    @staticmethod
    def parse_error_comments(error_file, price_map):
        wb = openpyxl.load_workbook(error_file)
        ws = wb.active
        results = []
        for row in range(10, ws.max_row + 1):
            orig_row_data = {
                "asins_raw": str(ws.cell(row=row, column=1).value or ""),
                "discount_type": ws.cell(row=row, column=2).value,
                "orig_discount": ws.cell(row=row, column=3).value,
                "name": ws.cell(row=row, column=5).value,
                "budget": ws.cell(row=row, column=6).value,
                "start": ws.cell(row=row, column=7).value,
                "end": ws.cell(row=row, column=8).value
            }
            if not orig_row_data["asins_raw"] or orig_row_data["asins_raw"] == "None": continue

            cell_n = ws.cell(row=row, column=14)
            error_text = cell_n.comment.text if cell_n.comment else ""
            row_asins = [a.strip() for a in orig_row_data["asins_raw"].split(';') if a.strip()]
            
            # 改进正则：确保能抓取到每个 ASIN 对应的独立报错
            error_blocks = re.findall(r'([A-Z0-9]{10})(.*?)(?=[A-Z0-9]{10}|$)', error_text, re.DOTALL)
            error_dict = {asin.strip(): msg.strip() for asin, msg in error_blocks}

            for sn in row_asins:
                current_p = price_map.get(sn, 0.0)
                msg = error_dict.get(sn, "")
                
                item = {
                    "row": row,
                    "asin": sn,
                    "original_price": current_p,
                    "amazon_target_price": "N/A",
                    "calc_discount": str(orig_row_data["orig_discount"]) + "%",
                    "decision": "✅ 正常 (保留)",
                    "type": "KEEP",
                    "orig_data": orig_row_data
                }

                if sn in error_dict:
                    if any(x in msg for x in ["没有经验证", "参考价", "历史售价"]):
                        item.update({"decision": "❌ 无参考价 (剔除)", "calc_discount": "剔除", "type": "REMOVE"})
                    elif "要求的净价格" in msg:
                        target_match = re.search(r'(?:价格|price)：?\s*[€\$]?\s*([\d\.]+)', msg)
                        target_p = float(target_match.group(1)) if target_match else 0.0
                        if current_p > 0 and target_p > 0:
                            needed = math.ceil(((current_p - target_p) / current_p) * 100)
                            final_pct = max(5, min(needed, 50))
                            item.update({
                                "amazon_target_price": target_p,
                                "calc_discount": f"{final_pct}%",
                                "decision": "⚠️ 力度不足 (需增加)",
                                "type": "ADJUST",
                                "new_pct_val": final_pct
                            })
                results.append(item)
        return results

# --- Streamlit UI 逻辑 ---
st.set_page_config(page_title="Coupon 智能修复看板", layout="wide")
st.title("⚖️ Coupon 报错对齐与全量整合")

with st.sidebar:
    st.header("1. 基础数据上传")
    list_file = st.file_uploader("上传 ALL Listing Report", type=['txt', 'csv'])
    err_file = st.file_uploader("上传亚马逊报错文件", type=['xlsx'])

if list_file and err_file:
    # 加载价格
    df_l = pd.read_csv(list_file, sep='\t' if list_file.name.endswith('.txt') else ',')
    p_map, p_col_name = CouponAccountingIntegrator.get_price_map(df_l)
    
    # 核心解析
    items = CouponAccountingIntegrator.parse_error_comments(err_file, p_map)
    
    # --- 关键功能：状态筛选器 ---
    st.divider()
    st.subheader("🔍 状态筛选排查")
    all_status = ["❌ 无参考价 (剔除)", "⚠️ 力度不足 (需增加)", "✅ 正常 (保留)"]
    
    # 默认只勾选报错的项，隐藏正常的项
    selected_status = st.multiselect(
        "选择要查看的 ASIN 状态：", 
        options=all_status,
        default=["❌ 无参考价 (剔除)", "⚠️ 力度不足 (需增加)"]
    )
    
    # 过滤数据
    filtered_items = [it for it in items if it['decision'] in selected_status]
    
    # --- 渲染表格 ---
    if not filtered_items:
        st.info("当前筛选条件下没有匹配的 ASIN。")
    else:
        display_df = []
        for it in filtered_items:
            display_df.append({
                "原行号": it['row'],
                "ASIN": it['asin'],
                "ASIN 原价": f"€{it['original_price']}",
                "亚马逊要求净价": f"€{it['amazon_target_price']}" if isinstance(it['amazon_target_price'], float) else it['amazon_target_price'],
                "决策状态": it['decision'],
                "建议折扣": it['calc_discount']
            })
        
        st.dataframe(pd.DataFrame(display_df), use_container_width=True, hide_index=True)

    # --- 最终整合导出 ---
    st.divider()
    st.subheader("🏗️ 最终提报缝合")
    if st.button("🚀 生成修复后的全量 ASIN 序列", type="primary"):
        # 逻辑：即使没被筛选出来的“正常项”也会参与缝合
        final_groups = {} 
        for it in items:
            if it['type'] == "REMOVE": continue
            
            # 确定折扣：如果是保留项用原折扣，如果是调整项用新计算的折扣
            try:
                final_pct = int(it['orig_data']['orig_discount']) if it['type'] == "KEEP" else it.get('new_pct_val')
            except:
                final_pct = it.get('new_pct_val', 5)
            
            if final_pct not in final_groups:
                final_groups[final_pct] = []
            final_groups[final_pct].append(it['asin'])

        for pct, asins in final_groups.items():
            with st.expander(f"📦 重新提报组：{pct}% 折扣 (共 {len(asins)} 个 ASIN)"):
                st.code("; ".join(asins))
                st.button("复制序列", key=f"copy_{pct}", on_click=lambda x=asins: st.write(f"已选中 {len(x)} 个ASIN"))
