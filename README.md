# 🎓 Teacher Assistant Telegram Bot

Bot Telegram hỗ trợ giáo viên quản lý công việc, tự động nhắc nhở và thống kê dựa trên tài liệu Word/Excel từ Google Drive.

## ✨ Tính năng

- 📥 **Đồng bộ Google Drive** — Tự động đọc file Word/Excel từ thư mục cố định
- 🔍 **Document Parser** — Hỗ trợ cột tiếng Việt, tự nhận diện header
- ⏰ **Nhắc nhở tự động** — Trước 3 ngày, 1 ngày, đúng hạn, quá hạn
- 📊 **Thống kê** — Tổng quan, theo lớp, theo học sinh
- 👩‍🎓 **Quản lý học sinh** — Tra cứu, theo dõi vấn đề
- 📄 **Báo cáo** — Xuất báo cáo chi tiết

## 🚀 Cài đặt nhanh

### 1. Tạo Telegram Bot

1. Mở Telegram, tìm [@BotFather](https://t.me/BotFather)
2. Gửi `/newbot` và làm theo hướng dẫn
3. Copy **token** được cấp

### 2. Clone & Cấu hình

```bash
# Clone project
cd teacher-bot

# Tạo virtual environment
python -m venv venv
source venv/bin/activate  # macOS/Linux

# Cài dependencies
pip install -r requirements.txt

# Cấu hình
cp .env.example .env
# Mở .env và điền TELEGRAM_BOT_TOKEN
```

### 3. Test với Mock Data

```bash
# Chạy test (không cần Google Drive)
python test_import.py
```

### 4. Chạy Bot

```bash
python -m bot.main
```

## 📁 Cấu trúc tài liệu

Bot hỗ trợ đọc bảng từ file **Excel** và **Word** với các cột sau:

### File Excel (ThongKe_HocSinh.xlsx)

| Cột | Bắt buộc | Mô tả |
|-----|----------|-------|
| Họ tên | ❌ | Tên học sinh |
| Lớp | ❌ | Mã lớp (10A1, 10A2...) |
| Môn | ❌ | Môn học |
| Vấn đề / Nội dung | ✅ | Nội dung công việc |
| Loại | ❌ | nhắc nhở / khen thưởng / kỷ luật |
| Deadline | ❌ | Ngày hạn (dd/mm/yyyy) |
| Trạng thái | ❌ | Chưa xử lý / Hoàn thành |

> 💡 Bot tự nhận diện tên cột bằng tiếng Việt (có dấu hoặc không dấu đều được)

### File Word (KeHoach_CongViec.docx)

Tương tự, bot đọc **bảng** trong file Word.

## 🔧 Thiết lập Google Drive

### 1. Tạo Service Account

1. Vào [Google Cloud Console](https://console.cloud.google.com/)
2. Tạo project mới (hoặc dùng project có sẵn)
3. Bật **Google Drive API**: APIs & Services → Library → Google Drive API → Enable
4. Tạo Service Account: APIs & Services → Credentials → Create Credentials → Service Account
5. Tạo key JSON: Click vào Service Account → Keys → Add Key → JSON
6. Lưu file JSON vào `credentials/service_account.json`

### 2. Chia sẻ thư mục

1. Tạo thư mục trên Google Drive chứa các file tài liệu
2. Click chuột phải → Share → Nhập email của Service Account (có dạng `xxx@xxx.iam.gserviceaccount.com`)
3. Copy **Folder ID** từ URL: `https://drive.google.com/drive/folders/FOLDER_ID_HERE`
4. Điền vào `.env`:
   ```
   GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here
   ```

## 🐳 Deploy với Docker

```bash
# Build & chạy
docker compose up -d

# Xem logs
docker compose logs -f

# Dừng
docker compose down
```

## 📋 Các lệnh Bot

| Lệnh | Mô tả |
|-------|-------|
| `/start` | Đăng ký & xem hướng dẫn |
| `/help` | Xem chi tiết các lệnh |
| `/today` | Việc cần làm hôm nay |
| `/week` | Việc trong 7 ngày tới |
| `/overdue` | Các việc quá hạn |
| `/thongke` | Thống kê tổng quan |
| `/hocsinh <tên>` | Tra cứu học sinh |
| `/lop <lớp>` | Thống kê theo lớp |
| `/hoanthanh <id>` | Đánh dấu hoàn thành |
| `/sync` | Đồng bộ Google Drive |
| `/baocao` | Báo cáo chi tiết |

## 🏗️ Kiến trúc

```
teacher-bot/
├── bot/
│   ├── main.py          # Entry point
│   └── handlers.py      # Xử lý lệnh Telegram
├── services/
│   ├── parser.py        # Parse Excel/Word
│   ├── gdrive.py        # Google Drive API
│   └── scheduler.py     # APScheduler jobs
├── database/
│   ├── models.py        # SQLAlchemy models
│   └── crud.py          # Database operations
├── mock_data/
│   └── generate_mock.py # Tạo dữ liệu mẫu
├── config.py            # Cấu hình từ .env
├── test_import.py       # Test nhanh
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 📝 License

MIT
