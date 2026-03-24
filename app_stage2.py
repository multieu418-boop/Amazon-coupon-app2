import streamlit as st
import pandas as pd
import openpyxl
import re
from io import BytesIO
import math

class CouponRepairEngine:
    @staticmethod
    def parse_errors(error_file, listing_df):
        # 使用 openpyxl 加载，确保读取批注
        wb = openpyxl.load_workbook(error_file)
        ws = wb.active
        
        # 建立 All Listing 价格映射
        asin_col = next((c for c in listing_df.columns if 'asin' in c.lower()), listing_df.columns[0])
        price_col = next((c for c in listing_df.columns if 'price' in c.lower()), listing_df.columns[1])
        price_map = pd.Series(listing_df[price_col].values, index=listing_df[asin_col]).to_dict()

        all_errors = []
        
        # 遍历所有数据行（从第10行开始）
        for row in range(10, ws.max_row + 1):
            # 亚马逊报错通常在 N 列（第14列）
            cell = ws.cell(row=row, column=14)
            
            # 关键：检查批注是否存在
            if cell.comment:
                full_msg = cell.comment.text
                
                # 识别当前行的原始 ASIN 集合（第一列）
                row_asins_raw = str(ws.cell(row=row, column=1).value or "")
                row_asins = [a.strip() for a in row_asins_raw.split(';') if a.strip()]

                # 逻辑优化：有些批注里包含多个 ASIN 的错误，我们需要拆分处理
                # 按换行符拆分批注，尝试匹配每一个 ASIN 的错误
                segments = full_msg.split('\n')
                for seg in segments:
                    if not seg.strip(): continue
                    
                    # 提取该段文字中的 ASIN
                    asin_match = re.search(r'[A-Z0-9]{10}', seg)
                    target_asin = asin_match.group(0) if asin_match else (row_asins[0] if row_asins else "未知")
                    
                    curr_p = price_map.get(target_asin, 0)
                    
                    # --- 识别错误类型 ---
                    # 1. 无参考价
                    if any(x in seg for x in ["没有经验证", "参考价", "历史售价", "Reference Price"]):
                        all_errors.append({
                            "asin": target_asin,
                            "row": row,
                            "reason": "❌ 无参考价 (需剔除)",
                            "msg": seg,
                            "curr_p": curr_p,
                            "type": "REMOVE",
                            "suggested": "剔除"
                        })
                    
                    # 2. 折扣力度不足
                    elif any(x in seg for x in ["要求", "净价格", "提高", "Required net price"]):
                        # 提取要求价格
                        price_match = re.search(r'[\d\.]+', seg.split("价格")[-1]) if "价格" in seg else re.search(r'[\d\.]+', seg)
                        target_p = float(price_match.group(0)) if price_match else 0
                        
                        if curr_p > 0 and target_p > 0:
                            # 计算折扣并向上取整
                            needed = math.ceil(((curr_p - target_p) / curr_p) * 100)
                            needed = max(5, min(needed, 50))
                            
                            all_errors.append({
                                "asin": target_asin,
                                "row": row,
                                "reason": f"⚠️ 力度不足 (限价 {target_p})",
                                "msg": seg,
                                "curr_p": curr_p,
                                "target_p": target_p,
                                "type": "ADJUST",
                                "suggested": f"{needed}%"
                            })
                        else:
                            all_errors.append({
                                "asin": target_asin,
                                "row": row,
                                "reason": "⚠️ 力度不足 (价格缺失)",
                                "msg": seg,
                                "curr_p": curr_p,
                                "type": "MANUAL",
                                "suggested": "手动核对"
                            })
        return all_errors

# --- 完整 UI 逻辑 ---
st.set_page_config(page_title="Amazon Coupon 修复版", layout="wide")
st.title("🛡️ Coupon 报错全量解析看板")

# (此处省略文件上传 UI 代码，与之前一致)
