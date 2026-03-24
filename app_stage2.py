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
        # 常见价格列名关键词
        price_keywords = ['price', 'your-price', '价格', 'amount', 'retail-price']
        asin_keywords = ['asin', 'sku-asin', '商品编码']
        
        target_price_col = None
        target_asin_col = None
        
        for col in df.columns:
            col_lower = str(col).lower()
            if any(k in col_lower for k in price_keywords) and target_price_col is None:
                target_price_col = col
            if any(k in col_lower for k in asin_keywords) and target_asin_col is None:
                target_asin_col = col
        
        # 建立映射
        if target_asin_col and target_price_col:
            df[target_asin_col] = df[target_asin_col].astype(str).str.strip().str.upper()
            return df.set_index(target_asin_col)[target_price_col].to_dict(), target_price_col
        return {}, "未找到价格列"

    @staticmethod
    def parse_error_comments(error_file, price_map):
        wb = openpyxl.load_workbook(error_file)
        ws = wb.active
        
        results = []
        # 遍历第10行开始的数据
        for row in range(10, ws.max_row + 1):
            # 获取原始填写的全部信息 (用于后续缝合)
            orig_row_data = {
                "asins_raw": str(ws.cell(row=row, column=1).value or ""),
                "discount_type": ws.cell(row=row, column=2).value,
                "orig_discount": ws.cell(row=row, column=3).value,
                "name": ws.cell(row=row, column=5).value,
                "budget": ws.cell(row=row, column=6).value,
                "start": ws.cell(row=row, column=7).value,
                "end": ws.cell(row=row, column=8).value
            }
            
            if not orig_row_data["asins_raw"]: continue

            # 解析 N 列报错
            cell_n = ws.cell(row=row, column=14)
            error_text = cell_n.comment.text if cell_n.comment else ""
            
            # 将该行所有 ASIN 拆分
            row_asins = [a.strip() for a in orig_row_data["asins_raw"].split(';') if a.strip()]
            
            # 识别报错块
            error_blocks = re.findall(r'([A-Z0-9]{10})(.*?)(?=[A-Z0-9]{10}|$)', error_text, re.DOTALL)
            error_dict = {asin: msg for asin, msg in error_blocks}

            for sn in row_asins:
                current_p = price_map.get(sn, 0.0)
                msg = error_dict.get(sn, "")
                
                item = {
                    "row": row,
                    "asin": sn,
                    "original_price": current_p,
                    "amazon_target_price": "N/A",
                    "calc_discount": "保持原样",
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
                            # 计算公式
                            needed = math.ceil(((current_p - target_p) / current_p) * 100)
                            final_pct = max(5, min(needed, 50))
                            item.update({
                                "amazon_target_price": target_p,
                                "calc_discount": f"{final_pct}%",
                                "decision": "⚠️ 力度不足 (需增加)",
                                "type": "ADJUST",
                                "new_pct_val": final_pct
                            })
                        else:
                            item.update({"decision": "❗ 价格缺失 (手动)", "calc_discount": "需检查", "type": "MANUAL"})
                
                results.append(item)
        return results, wb

# --- Streamlit UI ---
st.set_page_config(page_title="Coupon 决策中心", layout="wide")
st.title("🛡️ 阶段 2：报错 ASIN 财务对齐与全量缝合")

with st.sidebar:
    st.header("1. 数据导入")
    list_file = st.file_uploader("上传 ALL Listing Report", type=['txt', 'csv'])
    err_file = st.file_uploader("上传亚马逊报错文件", type=['xlsx'])

if list_file and err_file:
    # 加载价格
    df_l = pd.read_csv(list_file, sep='\t' if list_file.name.endswith('.txt') else ',')
    p_map, p_col_name = CouponAccountingIntegrator.get_price_map(df_l)
    st.sidebar.info(f"已识别价格列: {p_col_name}")
    
    # 解析报错
    items, original_wb = CouponAccountingIntegrator.parse_error_comments(err_file, p_map)
    
    # --- 渲染表格 ---
    st.subheader("📋 每一个 ASIN 的详细对齐报告")
    
    display_data = []
    for it in items:
        display_data.append({
            "原行号": it['row'],
            "ASIN": it['asin'],
            "ASIN 原价 (All Listing)": f"€{it['original_price']}",
            "亚马逊要求净价格": f"€{it['amazon_target_price']}" if isinstance(it['amazon_target_price'], float) else it['amazon_target_price'],
            "当前状态": it['decision'],
            "建议折扣力度": it['calc_discount']
        })
    
    st.table(pd.DataFrame(display_data))

    # --- 最终整合逻辑 ---
    st.divider()
    st.subheader("🏗️ 最终提报整合预览")
    
    if st.button("🚀 开始缝合：保留正常 ASIN + 修复报错 ASIN", type="primary"):
        # 按“新折扣力度”归类所有要保留的 ASIN
        # 1. 正常 ASIN 归类到原折扣
        # 2. 报错但增加力度的 ASIN 归类到新折扣
        final_groups = {} # {折扣值: [ASIN列表]}
        
        for it in items:
            if it['type'] == "REMOVE": continue
            
            # 确定该 ASIN 最终采用的折扣
            final_pct = it['orig_data']['orig_discount'] if it['type'] == "KEEP" else it.get('new_pct_val')
            
            if final_pct not in final_groups:
                final_groups[final_pct] = []
            final_groups[final_pct].append(it['asin'])

        # 显示整合结果
        for pct, asins in final_groups.items():
            with st.expander(f"📦 新 Coupon 提报组 - 折扣力度: {pct}%"):
                st.write(f"共包含 {len(asins)} 个 ASIN")
                st.code("; ".join(asins))
                st.caption("提示：您可以将此列表复制回阶段 1 生成新提报。")
