# Ish jarayonini nazorat qiluvchi Telegram bot

Bot 4 xil rol uchun ishlaydi va "ADMINLAR" hamda "NAZORATCHI ADMIN" uchun ish talablarini raqamlashtiradi:

| Rol | Vazifasi |
|---|---|
| **Montajchi** | Tayyorlagan videolarini kino kodi bilan qayd qiladi |
| **Admin** | Videoni 6 bandli tekshiruvdan o'tkazadi, Instagram → TikTok → YouTube → Telegram tartibida joylaydi, Story qo'yadi |
| **Nazoratchi admin** | Barcha ishni kuzatadi, muammolarni hal qiladi/eskalatsiya qiladi, kun davomida eslatma va skrinshot qo'shadi, kunlik PDF hisobotni Big Adminga yuboradi |
| **Big Admin** | Kunlik PDF hisobotni va jiddiy (eskalatsiya qilingan) muammolarni oladi |

Rol **Telegram user_id** asosida `.env` faylida belgilanadi. Hech qaysi ro'yxatda bo'lmagan odam botdan foydalana olmaydi — bot unga faqat ID raqamini ko'rsatadi (rahbarga yuborishi uchun).

## 1. O'rnatish

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Sozlash

1. **@BotFather** orqali yangi bot yarating va tokenni oling.
2. Nusxa oling: `cp .env.example .env`
3. `.env` faylini to'ldiring:
   - `BOT_TOKEN` — BotFather bergan token
   - `BIG_ADMIN_IDS`, `SUPERVISOR_IDS`, `MONTAJCHI_IDS`, `ADMIN_IDS` — har bir xodimning Telegram `user_id`si (**@userinfobot** orqali yoki botga `/start` yozib biling). `.env` o'zgartirilgach botni qayta ishga tushiring.
   - `GROUP_CHAT_ID` — muammo va e'lonlar tushadigan ish guruhi ID si (botni guruhga qo'shib, **@userinfobot** yordamida aniqlang; odatda manfiy son)
   - `MIN_STORIES_PER_PLATFORM`, `REMINDER_TIMES`, `REPORT_TIME`, `TIMEZONE`, `CONVERSATION_TIMEOUT_MIN` — kerak bo'lsa moslashtiring

> `assets/fonts/` papkasidagi shrift fayllarini (PDF hisobot uchun, o'zbekcha belgilarni to'g'ri chizadi) o'chirmang — ular loyihaga ilova qilingan.

## 3. Ishga tushirish

```bash
python bot.py
```

Har bir xodim botga `/start` yozadi — bot uning ID siga qarab rolini avtomatik aniqlaydi va mos menyuni ko'rsatadi.

## 4. Rollar bo'yicha menyu

**Montajchi:** 🎬 Video tayyor (8 bandli talablar tekshiruvi → kino kodi) · ⚠️ Muammo haqida xabar · 📊 Hisobot. Kunlik me'yor — `MIN_MONTAJ_VIDEOS` (standart 10); bajarilmasa eslatma keladi.

**Admin:** 🎬 Yangi video (6 bandli tekshiruv → kino kodi → 4 platformaga navbat bilan opisaniya + joylangan post havolasi) · 📖 Story qo'ydim (platforma + skrinshot) · ⚠️ Muammo haqida xabar · 📊 Hisobot

**Telegram kanalga avto-joylash** (`CHANNEL_ID` sozlangan bo'lsa): kino kodidan keyin admin videoning o'zini botga yuboradi. Telegram navbati kelganda admin faqat opisaniya yozadi, bot kanaldagi ko'rinishini oldindan ko'rsatadi va **✅ Kanalga joylash** bosilgach videoni kanalga o'zi joylaydi. Post havolasi avtomatik yoziladi. Joylab bo'lmasa (masalan, bot kanalda admin emas), bot qo'lda joylab, havolasini yuborishni so'raydi. Bot kanalga "Xabar joylash" huquqi bilan admin qilib qo'shilishi kerak.

Kino kodi kiritilganda bot tekshiradi: bu kod bilan avval video joylanganmi (dublikat) va montajchi bu kodni qayd etganmi. Muammo bo'lsa admin ogohlantiriladi; baribir davom etsa, ogohlantirish nazoratchiga ham boradi.

Boshlangan amal `/bekor_qilish` bilan, boshqa menyu tugmasini bosish bilan yoki `CONVERSATION_TIMEOUT_MIN` daqiqa javob bo'lmasa bekor bo'ladi.

**Nazoratchi admin:**
- 📸 Skrinshot qo'shish / 📝 Eslatma qo'shish — kun davomida kunlik PDF hisobotga material yig'adi (eslatma turi: aniqlangan xato yoki boshqa bajarilgan ish)
- 🗂 Ochiq muammolar — barcha hal qilinmagan muammolar (oldingi kunlardagilari ham), har biri ostida **✅ Hal qilindi** / **🔺 Big Adminga yuborish** tugmalari (bu tugmalar admin/montajchi yuborgan har bir muammo xabari ostida ham chiqadi)
- 📄 PDF hisobotni yuborish — qo'lda darhol yuborish
- 📊 Hisobot — barcha xodimlarning joriy kun ko'rsatkichlari (matn ko'rinishida)

**Big Admin:** 📊 Hisobot (istalgan payt matnli ko'rinishda), PDF hisobot va eskalatsiya qilingan muammolar avtomatik keladi.

## 5. Kunlik PDF hisobot

Hisobotga quyidagilar avtomatik yig'iladi:
1. Montajchi tayyorlagan videolar soni (me'yorga nisbatan, masalan 7/10) va kino kodlari
2. Har bir adminning joylagan videolari va Story ko'rsatkichlari
3. Barcha ijtimoiy tarmoqlarda joylangan videolar soni, havolalari va **montajchi tayyorlagan, lekin hali joylanmagan videolar** ro'yxati (oxirgi `UNPOSTED_LOOKBACK_DAYS` kun)
4. Kun davomidagi muammolar va ularning holati (hal qilingan / hal qilinmagan / eskalatsiya qilingan)
5. Nazoratchi kiritgan aniqlangan xatolar
6. Nazoratchi kiritgan boshqa bajarilgan ishlar
7. Nazoratchi kun davomida yuklagan skrinshotlar

Hisobotda shuningdek joylangan har bir videoning platformalardagi havolalari va oldingi kunlardan ochiq qolgan muammolar ham bo'ladi.

Hisobot **`REPORT_TIME`**da (standart 23:00, `.env`; `00:05` kabi tungi vaqt berilsa — kechagi kun uchun) avtomatik yaratilib, barcha `BIG_ADMIN_IDS`ga PDF fayl sifatida yuboriladi. Nazoratchi istalgan payt **📄 PDF hisobotni yuborish** tugmasi bilan qo'lda ham yuborishi mumkin.

## 6. Muammoni hal qilish / eskalatsiya

Admin yoki montajchi "⚠️ Muammo" orqali dalil (skrinshot/video) va tavsif yuborganda, xabar nazoratchi(lar)ga va ish guruhiga ✅/🔺 tugmalari bilan yetadi:
- **✅ Hal qilindi** — muammo yopiladi, hisobotda "hal qilindi" deb belgilanadi.
- **🔺 Big Adminga yuborish** — muammo darhol (dalili bilan) Big Adminga forward qilinadi va "eskalatsiya qilindi" deb belgilanadi.

## 7. Eslatmalar

`REMINDER_TIMES`da ko'rsatilgan vaqtlarda, kunlik Story me'yori (`MIN_STORIES_PER_PLATFORM`) to'liq bajarilmagan har bir adminga avtomatik shaxsiy eslatma yuboriladi. Ochiq muammolar bo'lsa, nazoratchilarga ham ro'yxat yuboriladi.

## 8. Ma'lumotlar bazasi va fayllar

- `bot.db` — SQLite ma'lumotlar bazasi, loyiha papkasida avtomatik yaratiladi (bot qaysi papkadan ishga tushirilishidan qat'i nazar). Zaxira nusxa uchun shu faylni nusxalash kifoya.
- `reports/` — yaratilgan PDF hisobotlar va skrinshotlar keshi shu yerda saqlanadi.

## 9. Doimiy ishlashi uchun (server)

```bash
nohup python bot.py > bot.log 2>&1 &
```

Yoki `systemd` / `pm2` / `tmux` orqali fon jarayoni sifatida ishga tushiring.

## 10. Kengaytirish g'oyalari

- Jarima/mukofot hisob-kitobini avtomatlashtirish (hisobot tarixi asosida oylik jamlanma)
- Web-panel orqali statistikani grafik ko'rish
- Ishdan bo'shatilgan/almashtirilgan xodim uchun rolni `.env`dan olib tashlab, yangisini qo'shish
