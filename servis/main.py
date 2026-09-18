import sqlite3
from datetime import date, timedelta
from pathlib import Path


import flet as ft
from persiantools.jdatetime import JalaliDate


# ============================================================
# تنظیمات
# ============================================================

DB_NAME = Path(__file__).with_name("service.db")


# ============================================================
# Database
# ============================================================

def get_db() -> sqlite3.Connection:
    """ایجاد اتصال جدید به دیتابیس."""
    db = sqlite3.connect(DB_NAME)
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db() -> None:
    """ساخت جداول در صورت نبودن آن‌ها."""
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS passengers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                fixed INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_passengers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                passenger_id INTEGER NOT NULL,
                service_date TEXT NOT NULL,
                FOREIGN KEY(passenger_id) REFERENCES passengers(id)
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS temporary_passengers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                service_date TEXT NOT NULL
            )
            """
        )

        # نسخه‌های قبلی فقط یک رکورد برای هر مسافر/روز داشتند.
        # حالا هر مسافر می‌تواند برای همان روز «رفت» و «برگشت» داشته باشد.
        columns = {
            row[1]
            for row in db.execute("PRAGMA table_info(daily_passengers)").fetchall()
        }

        if "direction" not in columns:
            db.execute(
                """
                ALTER TABLE daily_passengers
                ADD COLUMN direction TEXT NOT NULL DEFAULT 'رفت'
                """
            )

        # ایندکس قدیمی اجازه ثبت هم‌زمان رفت و برگشت را نمی‌دهد.
        db.execute("DROP INDEX IF EXISTS idx_daily_passenger_date")

        db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_daily_passenger_date_direction
            ON daily_passengers(passenger_id, service_date, direction)
            """
        )

        # مسیر ویژه هر روز؛ هر تاریخ فقط یک مسیر ویژه دارد.
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS special_routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_date TEXT NOT NULL UNIQUE,
                route_text TEXT NOT NULL DEFAULT ''
            )
            """
        )


def get_passengers():
    with get_db() as db:
        return db.execute(
            """
            SELECT id, name, phone
            FROM passengers
            WHERE active = 1
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()


def add_passenger(name: str, phone: str = "") -> None:
    with get_db() as db:
        db.execute(
            "INSERT INTO passengers (name, phone) VALUES (?, ?)",
            (name, phone),
        )


def delete_passenger(passenger_id: int) -> None:
    # حذف نرم: اطلاعات مسافر از دیتابیس پاک نمی‌شود.
    with get_db() as db:
        db.execute(
            "UPDATE passengers SET active = 0 WHERE id = ?",
            (passenger_id,),
        )


def get_daily_passengers(service_date: str) -> dict[int, set[str]]:
    """جهت‌های ثبت‌شده هر مسافر در تاریخ مشخص."""
    with get_db() as db:
        rows = db.execute(
            """
            SELECT passenger_id, direction
            FROM daily_passengers
            WHERE service_date = ?
            """,
            (service_date,),
        ).fetchall()

    result: dict[int, set[str]] = {}
    for passenger_id, direction in rows:
        result.setdefault(passenger_id, set()).add(direction)
    return result


def set_daily_passenger(
    passenger_id: int,
    service_date: str,
    direction: str,
    selected: bool,
) -> None:
    if direction not in {"رفت", "برگشت"}:
        raise ValueError("جهت سرویس نامعتبر است.")

    with get_db() as db:
        if selected:
            db.execute(
                """
                INSERT OR IGNORE INTO daily_passengers
                (passenger_id, service_date, direction)
                VALUES (?, ?, ?)
                """,
                (passenger_id, service_date, direction),
            )
        else:
            db.execute(
                """
                DELETE FROM daily_passengers
                WHERE passenger_id = ?
                  AND service_date = ?
                  AND direction = ?
                """,
                (passenger_id, service_date, direction),
            )


def get_special_route(service_date: str) -> str:
    with get_db() as db:
        row = db.execute(
            """
            SELECT route_text
            FROM special_routes
            WHERE service_date = ?
            """,
            (service_date,),
        ).fetchone()

    return row[0] if row else ""


def save_special_route(service_date: str, route_text: str) -> None:
    with get_db() as db:
        db.execute(
            """
            INSERT INTO special_routes (service_date, route_text)
            VALUES (?, ?)
            ON CONFLICT(service_date)
            DO UPDATE SET route_text = excluded.route_text
            """,
            (service_date, route_text),
        )


def get_monthly_special_routes(year: int, month: int):
    prefix = f"{year:04d}-{month:02d}-%"

    with get_db() as db:
        return db.execute(
            """
            SELECT service_date, route_text
            FROM special_routes
            WHERE service_date LIKE ?
              AND TRIM(route_text) <> ''
            ORDER BY service_date
            """,
            (prefix,),
        ).fetchall()

def add_temporary_passenger(
    name: str,
    phone: str,
    service_date: str,
) -> None:
    with get_db() as db:
        db.execute(
            """
            INSERT INTO temporary_passengers
            (name, phone, service_date)
            VALUES (?, ?, ?)
            """,
            (name, phone, service_date),
        )


def get_temporary_passengers(service_date: str):
    with get_db() as db:
        return db.execute(
            """
            SELECT id, name, phone
            FROM temporary_passengers
            WHERE service_date = ?
            ORDER BY id
            """,
            (service_date,),
        ).fetchall()


def delete_temporary_passenger(temp_id: int) -> None:
    with get_db() as db:
        db.execute(
            "DELETE FROM temporary_passengers WHERE id = ?",
            (temp_id,),
        )


# ============================================================
# Monthly Report
# ============================================================

def get_monthly_report(year: int, month: int):
    """گزارش ماهانه مسافران، جهت رفت/برگشت و مسیرهای ویژه."""
    prefix = f"{year:04d}-{month:02d}-%"

    with get_db() as db:
        fixed_rows = db.execute(
            """
            SELECT
                p.id,
                p.name,
                p.phone,
                SUM(CASE WHEN d.direction = 'رفت' THEN 1 ELSE 0 END) AS go_days,
                SUM(CASE WHEN d.direction = 'برگشت' THEN 1 ELSE 0 END) AS back_days
            FROM passengers p
            LEFT JOIN daily_passengers d
                ON d.passenger_id = p.id
               AND d.service_date LIKE ?
            WHERE p.active = 1
            GROUP BY p.id, p.name, p.phone
            ORDER BY p.name COLLATE NOCASE
            """,
            (prefix,),
        ).fetchall()

        temp_rows = db.execute(
            """
            SELECT name, phone, service_date
            FROM temporary_passengers
            WHERE service_date LIKE ?
            ORDER BY service_date, id
            """,
            (prefix,),
        ).fetchall()

        special_routes = db.execute(
            """
            SELECT service_date, route_text
            FROM special_routes
            WHERE service_date LIKE ?
              AND TRIM(route_text) <> ''
            ORDER BY service_date
            """,
            (prefix,),
        ).fetchall()

    return fixed_rows, temp_rows, special_routes



def get_monthly_report_rows(year: int, month: int):
    """تبدیل گزارش ماهانه به داده قابل نمایش در Flet."""
    fixed_rows, temp_rows, special_routes = get_monthly_report(year, month)

    result = []
    total_go = 0
    total_back = 0

    for _, name, phone, go_days, back_days in fixed_rows:
        go_days = int(go_days or 0)
        back_days = int(back_days or 0)
        total_go += go_days
        total_back += back_days

        # حتی اگر هنوز سرویس ثبت نشده، مسافر در گزارش باقی می‌ماند.
        result.append(
            {
                "name": name,
                "phone": phone or "-",
                "type": "ثابت",
                "go": go_days,
                "back": back_days,
            }
        )

    for name, phone, service_date in temp_rows:
        result.append(
            {
                "name": name,
                "phone": phone or "-",
                "type": "موقت",
                "go": "-",
                "back": "-",
                "date": service_date,
            }
        )

    return (
        result,
        len(fixed_rows),
        total_go,
        total_back,
        len(temp_rows),
        special_routes,
    )


# ============================================================
# Date
# ============================================================

def jalali_string(g_date: date) -> str:
    j_date = JalaliDate(g_date)
    return f"{j_date.year:04d}/{j_date.month:02d}/{j_date.day:02d}"


# ============================================================
# Application
# ============================================================

def main(page: ft.Page) -> None:
    init_db()

    page.title = "مدیریت سرویس"
    page.padding = 15
    page.theme_mode = ft.ThemeMode.LIGHT
    page.rtl = True
    page.scroll = ft.ScrollMode.AUTO

    current_date = date.today()

    title = ft.Text(
        "🚕 مدیریت سرویس",
        size=26,
        weight=ft.FontWeight.BOLD,
    )

    date_text = ft.Text(
        "",
        size=20,
        weight=ft.FontWeight.BOLD,
    )

    passenger_list = ft.Column(
        spacing=5,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    temp_list = ft.Column(
        spacing=5,
    )

    message = ft.Text("")

    # --------------------------------------------------------
    # پیام وضعیت
    # --------------------------------------------------------

    def set_message(text: str, error: bool = False) -> None:
        message.value = text
        message.color = ft.Colors.RED if error else ft.Colors.GREEN

    # --------------------------------------------------------
    # Refresh
    # --------------------------------------------------------

    def refresh(e=None) -> None:
        service_date = current_date.isoformat()

        date_text.value = f"تاریخ سرویس: {jalali_string(current_date)}"

        # مسافران ثابت
        passenger_list.controls.clear()

        selected = get_daily_passengers(service_date)

        for passenger_id, name, phone in get_passengers():
            go_checkbox = ft.Checkbox(
                label="رفت",
                value="رفت" in selected.get(passenger_id, set()),
            )
            back_checkbox = ft.Checkbox(
                label="برگشت",
                value="برگشت" in selected.get(passenger_id, set()),
            )

            def changed_go(
                event,
                pid=passenger_id,
                service_date=service_date,
            ):
                try:
                    set_daily_passenger(
                        pid,
                        service_date,
                        "رفت",
                        bool(event.control.value),
                    )
                    set_message("وضعیت «رفت» ذخیره شد.")
                except (sqlite3.Error, ValueError) as exc:
                    set_message(f"خطا در ذخیره‌سازی: {exc}", error=True)
                page.update()

            def changed_back(
                event,
                pid=passenger_id,
                service_date=service_date,
            ):
                try:
                    set_daily_passenger(
                        pid,
                        service_date,
                        "برگشت",
                        bool(event.control.value),
                    )
                    set_message("وضعیت «برگشت» ذخیره شد.")
                except (sqlite3.Error, ValueError) as exc:
                    set_message(f"خطا در ذخیره‌سازی: {exc}", error=True)
                page.update()

            go_checkbox.on_change = changed_go
            back_checkbox.on_change = changed_back

            passenger_list.controls.append(
                ft.Row(
                    controls=[
                        ft.Text(
                            name,
                            weight=ft.FontWeight.BOLD,
                            expand=True,
                        ),
                        ft.Text(
                            phone or "",
                            color=ft.Colors.GREY_600,
                        ),
                        go_checkbox,
                        back_checkbox,
                    ],
                )
            )

        # مسافران موقت
        temp_list.controls.clear()

        for temp_id, name, phone in get_temporary_passengers(service_date):

            def remove_temp(event, tid=temp_id):
                try:
                    delete_temporary_passenger(tid)
                    set_message("مسافر موقت حذف شد.")
                    refresh()
                except sqlite3.Error as exc:
                    set_message(f"خطا در حذف: {exc}", error=True)
                    page.update()

            temp_list.controls.append(
                ft.Row(
                    controls=[
                        ft.Text(f"⭐ {name}", size=16),
                        ft.Text(
                            phone or "",
                            color=ft.Colors.GREY_600,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE,
                            tooltip="حذف",
                            on_click=remove_temp,
                        ),
                    ],
                )
            )

        page.update()

    # --------------------------------------------------------
    # Change Date
    # --------------------------------------------------------

    def previous_day(e) -> None:
        nonlocal current_date
        current_date -= timedelta(days=1)
        set_message("")
        refresh()

    def next_day(e) -> None:
        nonlocal current_date
        current_date += timedelta(days=1)
        set_message("")
        refresh()

    def go_today(e) -> None:
        nonlocal current_date
        current_date = date.today()
        set_message("")
        refresh()

    # --------------------------------------------------------
    # Add fixed passenger
    # --------------------------------------------------------

    name_field = ft.TextField(
        label="نام مسافر",
        autofocus=True,
    )

    phone_field = ft.TextField(
        label="شماره تلفن",
        keyboard_type=ft.KeyboardType.PHONE,
    )

    def close_add_dialog(e=None) -> None:
        page.pop_dialog()

    def save_passenger(e) -> None:
        name = (name_field.value or "").strip()
        phone = (phone_field.value or "").strip()

        if not name:
            name_field.error_text = "نام مسافر الزامی است."
            page.update()
            return

        try:
            add_passenger(name, phone)

            name_field.value = ""
            phone_field.value = ""
            name_field.error_text = None

            page.pop_dialog()
            set_message("مسافر ثابت اضافه شد.")
            refresh()
        except sqlite3.Error as exc:
            set_message(f"خطا در افزودن مسافر: {exc}", error=True)
            page.update()

    add_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("افزودن مسافر ثابت"),
        content=ft.Column(
            controls=[name_field, phone_field],
            tight=True,
        ),
        actions=[
            ft.TextButton(
                content="انصراف",
                on_click=close_add_dialog,
            ),
            ft.TextButton(
                content="ذخیره",
                on_click=save_passenger,
            ),
        ],
    )

    def open_add_dialog(e) -> None:
        name_field.value = ""
        phone_field.value = ""
        name_field.error_text = None
        page.show_dialog(add_dialog)

    # --------------------------------------------------------
    # Temporary passenger
    # --------------------------------------------------------

    temp_name = ft.TextField(
        label="نام مسافر موقت",
    )

    temp_phone = ft.TextField(
        label="شماره تلفن",
        keyboard_type=ft.KeyboardType.PHONE,
    )

    def close_temp_dialog(e=None) -> None:
        page.pop_dialog()

    def save_temp(e) -> None:
        name = (temp_name.value or "").strip()
        phone = (temp_phone.value or "").strip()

        if not name:
            temp_name.error_text = "نام مسافر الزامی است."
            page.update()
            return

        try:
            add_temporary_passenger(
                name,
                phone,
                current_date.isoformat(),
            )

            temp_name.value = ""
            temp_phone.value = ""
            temp_name.error_text = None

            page.pop_dialog()
            set_message("مسافر موقت اضافه شد.")
            refresh()
        except sqlite3.Error as exc:
            set_message(f"خطا در افزودن مسافر موقت: {exc}", error=True)
            page.update()

    temp_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("مسافر موقت برای تاریخ انتخاب‌شده"),
        content=ft.Column(
            controls=[temp_name, temp_phone],
            tight=True,
        ),
        actions=[
            ft.TextButton(
                content="انصراف",
                on_click=close_temp_dialog,
            ),
            ft.TextButton(
                content="ذخیره",
                on_click=save_temp,
            ),
        ],
    )

    def open_temp_dialog(e) -> None:
        temp_name.value = ""
        temp_phone.value = ""
        temp_name.error_text = None
        page.show_dialog(temp_dialog)

    # --------------------------------------------------------
    # Special route for selected day
    # --------------------------------------------------------

    special_route_field = ft.TextField(
        label="مسیر ویژه این روز",
        hint_text="مثلاً: فرودگاه → مرکز شهر → برگشت",
        multiline=True,
        min_lines=2,
        max_lines=5,
    )

    special_route_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("مسیر ویژه روز"),
        content=ft.Container(
            content=special_route_field,
            width=600,
        ),
        actions=[
            ft.TextButton(
                content="انصراف",
                on_click=lambda e: page.pop_dialog(),
            ),
        ],
    )

    def open_special_route(e) -> None:
        special_route_field.value = get_special_route(
            current_date.isoformat()
        )
        special_route_dialog.actions = [
            ft.TextButton(
                content="بستن",
                on_click=lambda e: page.pop_dialog(),
            ),
            ft.TextButton(
                content="ذخیره",
                on_click=save_special_route_from_dialog,
            ),
        ]
        page.show_dialog(special_route_dialog)

    def save_special_route_from_dialog(e) -> None:
        route_text = (special_route_field.value or "").strip()

        try:
            save_special_route(current_date.isoformat(), route_text)
            page.pop_dialog()
            set_message("مسیر ویژه این روز ذخیره شد.")
            refresh()
        except sqlite3.Error as exc:
            set_message(f"خطا در ذخیره مسیر ویژه: {exc}", error=True)
            page.update()

    # --------------------------------------------------------
    # Passenger management
    # --------------------------------------------------------

    manage_list = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    def refresh_manage() -> None:
        manage_list.controls.clear()

        passengers = get_passengers()

        if not passengers:
            manage_list.controls.append(
                ft.Text("هنوز مسافر ثابتی ثبت نشده است.")
            )

        for pid, name, phone in passengers:

            def remove(event, passenger_id=pid):
                try:
                    delete_passenger(passenger_id)
                    set_message("مسافر غیرفعال شد.")
                    refresh_manage()
                    refresh()
                except sqlite3.Error as exc:
                    set_message(f"خطا در حذف: {exc}", error=True)
                    page.update()

            manage_list.controls.append(
                ft.Row(
                    controls=[
                        ft.Text(name, expand=True),
                        ft.Text(phone or ""),
                        ft.IconButton(
                            icon=ft.Icons.DELETE,
                            tooltip="حذف",
                            on_click=remove,
                        ),
                    ],
                )
            )

        page.update()

    manage_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("مدیریت مسافران ثابت"),
        content=ft.Container(
            content=manage_list,
            width=500,
            height=400,
        ),
        actions=[
            ft.TextButton(
                content="بستن",
                on_click=lambda e: page.pop_dialog(),
            )
        ],
    )

    def open_manage(e) -> None:
        refresh_manage()
        page.show_dialog(manage_dialog)

    # --------------------------------------------------------
    # Monthly report UI
    # --------------------------------------------------------

    report_year = current_date.year
    report_month = current_date.month

    report_content = ft.Column(
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
    )

    report_title = ft.Text(
        "",
        size=22,
        weight=ft.FontWeight.BOLD,
    )

    def build_report() -> None:
        report_content.controls.clear()

        (
            rows,
            fixed_count,
            total_go,
            total_back,
            temp_count,
            special_routes,
        ) = get_monthly_report_rows(report_year, report_month)

        report_title.value = (
            f"گزارش ماهانه {report_year:04d}/{report_month:02d}"
        )

        report_content.controls.append(
            ft.Text(
                f"مسافران ثابت: {fixed_count}   |   "
                f"رفت: {total_go}   |   "
                f"برگشت: {total_back}   |   "
                f"مسافران موقت: {temp_count}",
                size=16,
                weight=ft.FontWeight.BOLD,
            )
        )

        report_content.controls.append(ft.Divider())

        if rows:
            report_content.controls.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Text("نام", weight=ft.FontWeight.BOLD, expand=2),
                            ft.Text("تلفن", weight=ft.FontWeight.BOLD, expand=2),
                            ft.Text("نوع", weight=ft.FontWeight.BOLD, expand=1),
                            ft.Text("رفت", weight=ft.FontWeight.BOLD, expand=1),
                            ft.Text("برگشت", weight=ft.FontWeight.BOLD, expand=1),
                        ],
                        spacing=8,
                    ),
                    padding=8,
                )
            )

            for row in rows:
                extra_date = ""
                if row.get("date"):
                    extra_date = f" | {jalali_string(date.fromisoformat(row['date']))}"

                report_content.controls.append(
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text(row["name"], expand=2),
                                        ft.Text(row["phone"], expand=2),
                                        ft.Text(row["type"], expand=1),
                                        ft.Text(str(row["go"]), expand=1),
                                        ft.Text(str(row["back"]), expand=1),
                                    ],
                                    spacing=8,
                                ),
                                ft.Text(
                                    f"تاریخ مسافر موقت: {extra_date[3:]}"
                                    if extra_date
                                    else "",
                                    size=13,
                                    color=ft.Colors.GREY_600,
                                ) if extra_date else ft.Container(height=0),
                            ],
                            spacing=2,
                        ),
                        padding=8,
                        border=ft.Border.all(1, ft.Colors.GREY_300),
                        border_radius=6,
                    )
                )
        else:
            report_content.controls.append(
                ft.Text(
                    "برای این ماه هنوز مسافری ثبت نشده است.",
                    size=18,
                )
            )

        report_content.controls.append(ft.Divider())

        # مسیرهای ویژه ماه
        report_content.controls.append(
            ft.Text(
                "مسیرهای ویژه این ماه",
                size=20,
                weight=ft.FontWeight.BOLD,
            )
        )

        if special_routes:
            for service_date, route_text in special_routes:
                report_content.controls.append(
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Text(
                                    jalali_string(date.fromisoformat(service_date)),
                                    weight=ft.FontWeight.BOLD,
                                ),
                                ft.Text(route_text),
                            ],
                            spacing=4,
                        ),
                        padding=10,
                        border=ft.Border.all(1, ft.Colors.GREY_300),
                        border_radius=6,
                    )
                )
        else:
            report_content.controls.append(
                ft.Text("برای این ماه مسیر ویژه‌ای ثبت نشده است.")
            )

        report_content.controls.append(ft.Divider())

        report_content.controls.append(
            ft.Text(
                f"جمع رفت: {total_go}   |   جمع برگشت: {total_back}",
                size=18,
                weight=ft.FontWeight.BOLD,
            )
        )

    def report_previous_month(e) -> None:
        nonlocal report_year, report_month

        if report_month == 1:
            report_month = 12
            report_year -= 1
        else:
            report_month -= 1

        build_report()
        page.update()

    def report_next_month(e) -> None:
        nonlocal report_year, report_month

        if report_month == 12:
            report_month = 1
            report_year += 1
        else:
            report_month += 1

        build_report()
        page.update()

    def report_current_month(e) -> None:
        nonlocal report_year, report_month

        report_year = date.today().year
        report_month = date.today().month
        build_report()
        page.update()

    report_dialog = ft.AlertDialog(
        modal=True,
        title=report_title,
        content=ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Button(
                                content="ماه قبل",
                                on_click=report_previous_month,
                            ),
                            ft.Button(
                                content="ماه جاری",
                                on_click=report_current_month,
                            ),
                            ft.Button(
                                content="ماه بعد",
                                on_click=report_next_month,
                            ),
                        ],
                        wrap=True,
                    ),
                    report_content,
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=850,
            height=650,
        ),
        actions=[
            ft.TextButton(
                content="بستن",
                on_click=lambda e: page.pop_dialog(),
            )
        ],
    )

    def open_report(e) -> None:
        nonlocal report_year, report_month

        # پیش‌فرض: ماهی که در صفحه اصلی انتخاب شده است.
        report_year = current_date.year
        report_month = current_date.month
        build_report()
        page.show_dialog(report_dialog)

    # --------------------------------------------------------
    # Layout
    # --------------------------------------------------------

    page.add(
        ft.SafeArea(
            content=ft.Column(
                controls=[
                    title,

                    ft.Row(
                        controls=[
                            ft.Button(
                                content="روز قبل",
                                icon=ft.Icons.CHEVRON_LEFT,
                                on_click=previous_day,
                            ),
                            ft.Button(
                                content="امروز",
                                icon=ft.Icons.TODAY,
                                on_click=go_today,
                            ),
                            ft.Button(
                                content="روز بعد",
                                icon=ft.Icons.CHEVRON_RIGHT,
                                on_click=next_day,
                            ),
                        ],
                        wrap=True,
                    ),

                    date_text,

                    ft.Container(
                        content=ft.Row(
                            controls=[
                                ft.Text(
                                    "مسیر ویژه روز",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                ft.Button(
                                    content="ثبت / ویرایش مسیر ویژه",
                                    icon=ft.Icons.ALT_ROUTE,
                                    on_click=open_special_route,
                                ),
                            ],
                            wrap=True,
                        ),
                        padding=8,
                    ),

                    ft.Divider(),

                    ft.Text(
                        "مسافران ثابت (رفت / برگشت)",
                        size=20,
                        weight=ft.FontWeight.BOLD,
                    ),

                    ft.Container(
                        content=passenger_list,
                        height=300,
                        expand=True,
                    ),

                    ft.Divider(),

                    ft.Text(
                        "مسافران موقت در تاریخ انتخاب‌شده",
                        size=20,
                        weight=ft.FontWeight.BOLD,
                    ),

                    temp_list,

                    ft.Row(
                        controls=[
                            ft.Button(
                                content="+ مسافر ثابت",
                                icon=ft.Icons.PERSON_ADD,
                                on_click=open_add_dialog,
                            ),
                            ft.Button(
                                content="+ مسافر موقت",
                                icon=ft.Icons.PERSON_ADD_ALT,
                                on_click=open_temp_dialog,
                            ),
                            ft.Button(
                                content="مدیریت مسافران",
                                icon=ft.Icons.MANAGE_ACCOUNTS,
                                on_click=open_manage,
                            ),
                            ft.Button(
                                content="گزارش ماهانه",
                                icon=ft.Icons.RECEIPT_LONG,
                                on_click=open_report,
                            ),
                        ],
                        wrap=True,
                    ),

                    message,
                ],
                spacing=12,
            )
        )
    )

    refresh()


if __name__ == "__main__":
    ft.run(main)
