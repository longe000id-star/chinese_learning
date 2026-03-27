# utils/ocr.py
import os
import time
import tempfile
import zipfile
import io
import logging
import streamlit as st
from ocr_image_module import ocr_images_batch, BAIMIAO_CONFIG as IMAGE_OCR_CONFIG, format_results_as_text
from ocr_pdf_module import ocr_pdf, BAIMIAO_CONFIG as PDF_OCR_CONFIG

logger = logging.getLogger(__name__)

def process_ocr_images(uploaded_files):
    """处理图片OCR - 带详细日志"""
    if not uploaded_files:
        return None
    
    logger.info(f"=== OCR图片处理开始 ===")
    logger.info(f"上传图片数量: {len(uploaded_files)}")
    
    for idx, f in enumerate(uploaded_files):
        logger.info(f"  图片 {idx+1}: {f.name}, 大小: {f.size} bytes, 类型: {f.type}")
    
    if len(uploaded_files) > 300:
        logger.warning(f"图片数量超过300，只处理前300张")
        uploaded_files = uploaded_files[:300]
    
    image_list = []
    for f in uploaded_files:
        read_start = time.time()
        img_bytes = f.read()
        read_time = time.time() - read_start
        logger.info(f"读取图片 {f.name}: {read_time:.2f}秒, 大小: {len(img_bytes)/1024:.1f}KB")
        image_list.append((img_bytes, f.name))
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    def update_progress(current, total, filename, status, preview):
        progress_bar.progress(current / total)
        status_text.text(f"Processing: {current}/{total} - {filename} - {status}")
        logger.info(f"OCR进度: {current}/{total} - {filename} - {status}")
        if preview:
            logger.debug(f"  预览: {preview[:100]}...")
    
    ocr_start = time.time()
    logger.info("开始调用 ocr_images_batch...")
    
    try:
        results = ocr_images_batch(image_list, IMAGE_OCR_CONFIG, progress_callback=update_progress)
        ocr_time = time.time() - ocr_start
        logger.info(f"ocr_images_batch 完成，耗时: {ocr_time:.2f}秒")
        
        if results:
            success_count = sum(1 for r in results if r[1] == "success")
            failed_count = len(results) - success_count
            logger.info(f"OCR结果: 成功={success_count}, 失败={failed_count}")
            for filename, status, text in results:
                if status == "success":
                    logger.info(f"  ✅ {filename}: {len(text)} 字符")
                else:
                    logger.error(f"  ❌ {filename}: 识别失败")
        else:
            logger.warning("OCR结果为空")
            
    except Exception as e:
        logger.error(f"OCR处理异常: {e}", exc_info=True)
        results = None
    
    progress_bar.empty()
    status_text.empty()
    
    logger.info(f"=== OCR图片处理结束 ===")
    return results

def process_ocr_pdf(uploaded_pdf):
    """处理PDF OCR - 带详细日志"""
    if not uploaded_pdf:
        return None
    
    logger.info(f"=== OCR PDF处理开始 ===")
    logger.info(f"PDF文件: {uploaded_pdf.name}, 大小: {uploaded_pdf.size} bytes")
    
    read_start = time.time()
    pdf_bytes = uploaded_pdf.read()
    read_time = time.time() - read_start
    logger.info(f"读取PDF耗时: {read_time:.2f}秒, 大小: {len(pdf_bytes)/1024:.1f}KB")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    def update_progress(current, total, message):
        progress_bar.progress(current / total)
        status_text.text(f"OCR: {message}")
        logger.info(f"PDF OCR进度: {current}/{total} - {message}")
    
    ocr_start = time.time()
    logger.info("开始调用 ocr_pdf...")
    
    try:
        status, text = ocr_pdf(
            pdf_bytes,
            uploaded_pdf.name,
            PDF_OCR_CONFIG["cookie"],
            PDF_OCR_CONFIG["x_auth_token"],
            PDF_OCR_CONFIG["x_auth_uuid"],
            progress_callback=update_progress,
            config=PDF_OCR_CONFIG
        )
        
        ocr_time = time.time() - ocr_start
        logger.info(f"ocr_pdf 完成，耗时: {ocr_time:.2f}秒")
        
        if status == "success":
            logger.info(f"PDF OCR成功，文本长度: {len(text)} 字符")
        else:
            logger.error(f"PDF OCR失败，状态: {status}")
            
    except Exception as e:
        logger.error(f"PDF OCR异常: {e}", exc_info=True)
        status = "failed"
        text = None
    
    progress_bar.empty()
    status_text.empty()
    
    logger.info(f"=== OCR PDF处理结束 ===")
    
    if status == "success":
        return text
    else:
        return None