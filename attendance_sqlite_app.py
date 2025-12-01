# attendance_sqlite_app.py
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import io
from pathlib import Path
from io import BytesIO

# PDF libs
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ---------------------------
# CONFIG
# ---------------------------
DB_PATH = "attendance.db"
st.set_page_config(page_title="College Attendance (SQLite)", layout="wide")

# ---------------------------
# DB HELPERS
# ---------------------------
def get_conn():
    # Ensure DB file exists & tables are created before calling get_conn ideally.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # Colleges, Departments, Courses, Students, Attendance
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS colleges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            college_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(college_id, name),
            FOREIGN KEY(college_id) REFERENCES colleges(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(department_id, name),
            FOREIGN KEY(department_id) REFERENCES departments(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            roll TEXT,
            name TEXT NOT NULL,
            UNIQUE(course_id, roll),
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL,
            timestamp TEXT,
            UNIQUE(student_id, date),
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()
    conn.close()

# ---------------------------
# CRUD OPERATIONS
# ---------------------------
def add_college(name: str):
    conn = get_conn()
    try:
        conn.execute("INSERT INTO colleges(name) VALUES (?)", (name.strip(),))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False
    conn.close()
    return True

def list_colleges():
    conn = get_conn()
    rows = conn.execute("SELECT id, name FROM colleges ORDER BY name").fetchall()
    conn.close()
    # convert to list of dicts
    return [dict(r) for r in rows]

def add_department(college_id:int, name:str):
    conn = get_conn()
    try:
        conn.execute("INSERT INTO departments(college_id, name) VALUES (?,?)", (college_id, name.strip()))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False
    conn.close()
    return True

def list_departments(college_id:int):
    conn = get_conn()
    rows = conn.execute("SELECT id, name FROM departments WHERE college_id=? ORDER BY name", (college_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_course(department_id:int, name:str):
    conn = get_conn()
    try:
        conn.execute("INSERT INTO courses(department_id, name) VALUES (?,?)", (department_id, name.strip()))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False
    conn.close()
    return True

def list_courses(department_id:int):
    conn = get_conn()
    rows = conn.execute("SELECT id, name FROM courses WHERE department_id=? ORDER BY name", (department_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_student(course_id:int, name:str, roll:str=None):
    conn = get_conn()
    try:
        conn.execute("INSERT INTO students(course_id, name, roll) VALUES (?,?,?)", (course_id, name.strip(), roll.strip() if roll else None))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False
    conn.close()
    return True

def list_students(course_id:int):
    conn = get_conn()
    rows = conn.execute("SELECT id, name, roll FROM students WHERE course_id=? ORDER BY name", (course_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_attendance_for_date(student_status_map: dict, date_str: str):
    """
    student_status_map: { student_id: 'Present'/'Absent' }
    date_str: 'YYYY-MM-DD'
    """
    conn = get_conn()
    cur = conn.cursor()
    ts = datetime.now().isoformat(timespec='seconds')
    for sid, status in student_status_map.items():
        # Upsert: insert or update
        cur.execute("""
            INSERT INTO attendance(student_id, date, status, timestamp)
            VALUES (?,?,?,?)
            ON CONFLICT(student_id, date) DO UPDATE SET status=excluded.status, timestamp=excluded.timestamp
        """, (sid, date_str, status, ts))
    conn.commit()
    conn.close()
    return True

def get_attendance_df(filter_clause="", params=()):
    conn = get_conn()
    q = f"""
    SELECT a.id as att_id, s.id as student_id, s.name as student_name, s.roll as roll,
           c.id as course_id, c.name as course,
           d.id as department_id, d.name as department,
           co.id as college_id, co.name as college,
           a.date, a.status, a.timestamp
    FROM attendance a
    JOIN students s ON s.id = a.student_id
    JOIN courses c ON c.id = s.course_id
    JOIN departments d ON d.id = c.department_id
    JOIN colleges co ON co.id = d.college_id
    {filter_clause}
    ORDER BY a.date DESC, co.name, d.name, c.name, s.name
    """
    try:
        df = pd.read_sql_query(q, get_conn(), params=params)
    except Exception:
        df = pd.DataFrame()
    return df

# ---------------------------
# REPORT EXPORT HELPERS
# ---------------------------
def df_to_excel_bytes(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    return output.getvalue()


def df_to_pdf_bytes(df: pd.DataFrame, title="Attendance Report"):
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=letter)
    styles = getSampleStyleSheet()
    flow = []
    flow.append(Paragraph(title, styles['Title']))
    flow.append(Spacer(1,12))

    if df.empty:
        flow.append(Paragraph("No records", styles['Normal']))
    else:
        cols = list(df.columns)
        data = [cols]
        for _, row in df.iterrows():
            data.append([str(row[c]) for c in cols])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('GRID',(0,0),(-1,-1),0.5,colors.grey),
            ('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ]))
        flow.append(table)

    doc.build(flow)
    bio.seek(0)
    return bio

# ---------------------------
# UTILS
# ---------------------------
def ensure_db_file():
    # create DB file and tables if not exist
    if not Path(DB_PATH).exists():
        init_db()
    else:
        # Even if file exists, ensure tables exist (useful after code updates)
        init_db()

# ---------------------------
# UI: Sidebar - Quick Navigation
# ---------------------------
ensure_db_file()
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", [
    "Setup (Colleges/Dept/Course/Students)",
    "Mark Attendance",
    "Calendar View",
    "Reports & Export",
    "Admin"
])

# ---------------------------
# PAGE: Setup
# ---------------------------
if page == "Setup (Colleges/Dept/Course/Students)":
    st.header("🏫 Hexcent Attendance Portal")

    # Add college
    st.subheader("Add College")
    col_name = st.text_input("College name", key="col_name")
    if st.button("Add College"):
        if not col_name.strip():
            st.warning("Enter a valid college name.")
        else:
            ok = add_college(col_name)
            if ok:
                st.success(f"College '{col_name}' added.")
            else:
                st.error("College already exists.")
    st.markdown("---")

    # Choose college to add department
    colleges = list_colleges()
    if colleges:
        col_map = {str(r["name"]): r["id"] for r in colleges}
        sel_college_name = st.selectbox("Select College", list(col_map.keys()))
        sel_college_id = col_map[sel_college_name]

        # Add department
        st.subheader("Add Department")
        dept_name = st.text_input("Department name", key="dept_name")
        if st.button("Add Department"):
            if not dept_name.strip():
                st.warning("Enter department name.")
            else:
                ok = add_department(sel_college_id, dept_name)
                if ok:
                    st.success(f"Department '{dept_name}' added under {sel_college_name}.")
                else:
                    st.error("Department already exists in this college.")
        st.markdown("---")

        # Choose department - list
        depts = list_departments(sel_college_id)
        if depts:
            dept_map = {r["name"]: r["id"] for r in depts}
            sel_dept_name = st.selectbox("Select Department", list(dept_map.keys()))
            sel_dept_id = dept_map[sel_dept_name]

            # Add course
            st.subheader("Add Course")
            course_name = st.text_input("Course name", key="course_name")
            if st.button("Add Course"):
                if not course_name.strip():
                    st.warning("Enter course name.")
                else:
                    ok = add_course(sel_dept_id, course_name)
                    if ok:
                        st.success(f"Course '{course_name}' added under {sel_dept_name}.")
                    else:
                        st.error("Course already exists in this department.")
            st.markdown("---")

            # Choose course - list
            courses = list_courses(sel_dept_id)
            if courses:
                course_map = {r["name"]: r["id"] for r in courses}
                sel_course_name = st.selectbox("Select Course", list(course_map.keys()))
                sel_course_id = course_map[sel_course_name]

                # Add student
                st.subheader("Add Student")
                stu_name = st.text_input("Student full name", key="stu_name")
                stu_roll = st.text_input("Roll number (optional)", key="stu_roll")
                if st.button("Add Student"):
                    if not stu_name.strip():
                        st.warning("Enter student name.")
                    else:
                        ok = add_student(sel_course_id, stu_name, stu_roll)
                        if ok:
                            st.success(f"Student '{stu_name}' added to {sel_course_name}.")
                        else:
                            st.error("Student with same roll already exists in this course.")
                st.markdown("---")

                # Show students
                st.subheader("Students in selected course")
                students = list_students(sel_course_id)
                if students:
                    df_students = pd.DataFrame(students)
                    # ensure columns exist
                    if not df_students.empty:
                        df_students = df_students.rename(columns={"id":"student_id"})
                        cols_to_show = [c for c in ["student_id","name","roll"] if c in df_students.columns]
                        st.dataframe(df_students[cols_to_show], use_container_width=True)
                    else:
                        st.info("No students added to this course yet.")
                else:
                    st.info("No students added to this course yet.")
    else:
        st.info("No colleges yet. Add a college first.")

# ---------------------------
# PAGE: Mark Attendance
# ---------------------------
elif page == "Mark Attendance":
    st.header("📝 Mark Attendance (College → Dept → Course)")

    colleges = list_colleges()
    if not colleges:
        st.info("No colleges found. Add one in Setup.")
    else:
        col_map = {r["name"]: r["id"] for r in colleges}
        sel_college_name = st.selectbox("Select College", list(col_map.keys()))
        sel_college_id = col_map[sel_college_name]

        depts = list_departments(sel_college_id)
        if not depts:
            st.info("No departments found for this college. Add one in Setup.")
        else:
            dept_map = {r["name"]: r["id"] for r in depts}
            sel_dept_name = st.selectbox("Select Department", list(dept_map.keys()))
            sel_dept_id = dept_map[sel_dept_name]

            courses = list_courses(sel_dept_id)
            if not courses:
                st.info("No courses in this department. Add one in Setup.")
            else:
                course_map = {r["name"]: r["id"] for r in courses}
                sel_course_name = st.selectbox("Select Course", list(course_map.keys()))
                sel_course_id = course_map[sel_course_name]

                # Date picker
                date_sel = st.date_input("Attendance date", value=datetime.now().date(), key="att_date")
                date_str = date_sel.strftime("%Y-%m-%d")

                students = list_students(sel_course_id)
                if not students:
                    st.info("No students in this course. Add students in Setup.")
                else:
                    st.subheader(f"Mark Present Students for {sel_course_name} ({date_str})")
                    # Show current attendance for date
                    df_existing = get_attendance_df(filter_clause="WHERE a.date = ? AND c.id = ?", params=(date_str, sel_course_id))
                    existing_present_ids = set()
                    if not df_existing.empty and 'student_id' in df_existing.columns:
                        existing_present_ids = set(df_existing[df_existing['status']=="Present"]['student_id'].tolist())

                    # Use multiselect: list of student_id:name
                    options = [f"{r['id']}|{r['name']} ({r['roll'] if r.get('roll') else ''})" for r in students]
                    # default selected = existing present
                    default_sel = [opt for opt in options if int(opt.split("|")[0]) in existing_present_ids]

                    selected_present = st.multiselect("Select Present Students (others will be marked Absent)", options, default=default_sel, key="present_multiselect")
                    # prepare map
                    student_status_map = {}
                    for opt in options:
                        sid = int(opt.split("|")[0])
                        student_status_map[sid] = "Present" if opt in selected_present else "Absent"

                    if st.button("Save Attendance"):
                        mark_attendance_for_date(student_status_map, date_str)
                        st.success("Attendance saved.")

                    # show a quick attendance table for the date & course
                    df_show = get_attendance_df(filter_clause="WHERE a.date = ? AND c.id = ?", params=(date_str, sel_course_id))
                    if not df_show.empty:
                        st.subheader("Attendance saved (preview)")
                        cols_to_display = [c for c in ['college','department','course','student_name','roll','date','status'] if c in df_show.columns]
                        st.dataframe(df_show[cols_to_display], use_container_width=True)

# ---------------------------
# PAGE: Calendar View
# ---------------------------
elif page == "Calendar View":
    st.header("📅 Attendance Calendar View")
    # Filters
    colleges = list_colleges()
    if not colleges:
        st.info("No data yet.")
    else:
        col_map = {r["name"]: r["id"] for r in colleges}
        sel_college_name = st.selectbox("Filter by College (optional)", ["All"] + list(col_map.keys()))
        sel_dept_id = None
        sel_course_id = None

        if sel_college_name != "All":
            sel_college_id = col_map[sel_college_name]
            depts = list_departments(sel_college_id)
            dept_map = {r["name"]: r["id"] for r in depts}
            sel_dept_name = st.selectbox("Filter by Department (optional)", ["All"] + list(dept_map.keys()))
            if sel_dept_name != "All":
                sel_dept_id = dept_map[sel_dept_name]
                courses = list_courses(sel_dept_id)
                course_map = {r["name"]: r["id"] for r in courses}
                sel_course_name = st.selectbox("Filter by Course (optional)", ["All"] + list(course_map.keys()))
                if sel_course_name != "All":
                    sel_course_id = course_map[sel_course_name]

        # Date range
        st.write("Select date range to show calendar:")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start date", value=(datetime.now().date() - timedelta(days=14)), key="cal_start")
        with col2:
            end_date = st.date_input("End date", value=datetime.now().date(), key="cal_end")
        if start_date > end_date:
            st.error("Start date cannot be after end date.")
        else:
            # build filter
            clauses = []
            params = []
            if sel_college_name != "All":
                clauses.append("co.id = ?")
                params.append(sel_college_id)
            if sel_dept_id is not None:
                clauses.append("d.id = ?")
                params.append(sel_dept_id)
            if sel_course_id is not None:
                clauses.append("c.id = ?")
                params.append(sel_course_id)
            clauses.append("a.date BETWEEN ? AND ?")
            params.append(start_date.strftime("%Y-%m-%d"))
            params.append(end_date.strftime("%Y-%m-%d"))

            filter_clause = "WHERE " + " AND ".join(clauses)
            df = get_attendance_df(filter_clause=filter_clause, params=tuple(params))

            if df.empty:
                st.info("No attendance records in this range.")
            else:
                # pivot: rows = Student (with roll), columns = date, values = status
                if 'roll' not in df.columns:
                    df['roll'] = ""
                df['student_display'] = df['student_name'] + df['roll'].fillna('').apply(lambda x: (f" ({x})" if x else ""))
                pivot = df.pivot_table(index=['student_display','course','department','college'],
                                       columns='date', values='status', aggfunc='first').fillna("")
                st.dataframe(pivot, use_container_width=True)

# ---------------------------
# PAGE: Reports & Export
# ---------------------------
elif page == "Reports & Export":
    st.header("📤 Reports & Export")

    # Full data view
    st.subheader("Filter & Export")
    colleges = list_colleges()
    col_map = {r["name"]: r["id"] for r in colleges} if colleges else {}
    sel_college = st.selectbox("College (optional)", ["All"] + list(col_map.keys()))
    sel_dept = None; sel_course = None

    def build_filters_from_ui():
        clauses = []
        params = []
        if sel_college != "All":
            college_id = col_map[sel_college]
            clauses.append("co.id = ?"); params.append(college_id)
            depts = list_departments(college_id)
            dept_map = {r["name"]: r["id"] for r in depts}
            sel_dept_loc = st.selectbox("Department (optional)", ["All"] + list(dept_map.keys()))
            if sel_dept_loc != "All":
                dept_id = dept_map[sel_dept_loc]
                clauses.append("d.id = ?"); params.append(dept_id)
                courses = list_courses(dept_id)
                course_map = {r["name"]: r["id"] for r in courses}
                sel_course_loc = st.selectbox("Course (optional)", ["All"] + list(course_map.keys()))
                if sel_course_loc != "All":
                    course_id = course_map[sel_course_loc]
                    clauses.append("c.id = ?"); params.append(course_id)
        # date range
        start = st.date_input("Start date", value=(datetime.now().date() - timedelta(days=30)), key="rep_start")
        end = st.date_input("End date", value=datetime.now().date(), key="rep_end")
        clauses.append("a.date BETWEEN ? AND ?"); params.append(start.strftime("%Y-%m-%d")); params.append(end.strftime("%Y-%m-%d"))
        if clauses:
            return ("WHERE " + " AND ".join(clauses), tuple(params))
        else:
            return ("", ())

    filter_clause, params = build_filters_from_ui()
    df = get_attendance_df(filter_clause=filter_clause, params=params)
    if df.empty:
        st.info("No records for the selected filters.")
    else:
        cols_to_show = [c for c in ['college','department','course','student_name','roll','date','status'] if c in df.columns]
        st.dataframe(df[cols_to_show], use_container_width=True)

        # Export Excel
        excel_bio = df_to_excel_bytes(df)
        st.download_button("📥 Download Excel (filtered)", data=excel_bio, file_name=f"attendance_filtered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # Export PDF
        pdf_bio = df_to_pdf_bytes(df, title="Filtered Attendance Report")
        st.download_button("📄 Download PDF (filtered)", data=pdf_bio, file_name=f"attendance_filtered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf", mime="application/pdf")

    st.markdown("---")
    # Weekly report per student (Excel)
    st.subheader("Weekly Attendance Report (per student or whole course)")

    # Select course first
    all_colleges = list_colleges()
    if all_colleges:
        c_map = {r["name"]: r["id"] for r in all_colleges}
        c_choice = st.selectbox("Select College for weekly report", list(c_map.keys()))
        d_list = list_departments(c_map[c_choice])
        if d_list:
            d_map = {r["name"]: r["id"] for r in d_list}
            d_choice = st.selectbox("Select Department", list(d_map.keys()))
            crs = list_courses(d_map[d_choice])
            if crs:
                crs_map = {r["name"]: r["id"] for r in crs}
                crs_choice = st.selectbox("Select Course", list(crs_map.keys()))
                course_id_for_report = crs_map[crs_choice]
                students = list_students(course_id_for_report)
                if students:
                    student_map = {f"{r['id']}|{r['name']}": r['id'] for r in students}
                    student_choice = st.selectbox("Student (optional) - choose 'All' for every student", ["All"] + list(student_map.keys()))
                    # date range default to last 7 days
                    end_date = datetime.now().date()
                    start_date = st.date_input("Start date for weekly report", value=(end_date - timedelta(days=7)), key="weekly_start")
                    end_date = st.date_input("End date for weekly report", value=end_date, key="weekly_end")
                    if start_date > end_date:
                        st.error("Invalid date range.")
                    else:
                        if st.button("Generate Weekly Excel Report"):
                            clauses = ["a.date BETWEEN ? AND ?", "c.id = ?"]
                            params = [start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), course_id_for_report]
                            if student_choice != "All":
                                sid = int(student_choice.split("|")[0])
                                clauses.append("s.id = ?"); params.append(sid)
                            filter_clause = "WHERE " + " AND ".join(clauses)
                            df_week = get_attendance_df(filter_clause=filter_clause, params=tuple(params))
                            if df_week.empty:
                                st.warning("No attendance data in this date range.")
                            else:
                                # build a student-wise summary table
                                presences = df_week[df_week['status']=="Present"].groupby(['student_name','roll']).size().reset_index(name='PresentCount')
                                total_days = (end_date - start_date).days + 1
                                students_list = df_week[['student_name','roll']].drop_duplicates()
                                merged = students_list.merge(presences, on=['student_name','roll'], how='left').fillna(0)
                                merged['TotalDays'] = total_days
                                merged['PresentCount'] = merged['PresentCount'].astype(int)
                                merged['Attendance%'] = (merged['PresentCount'] / merged['TotalDays'] * 100).round(2)
                                bio = io.BytesIO()
                                with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
                                    merged.to_excel(writer, index=False, sheet_name="WeeklySummary")
                                    df_week.to_excel(writer, index=False, sheet_name="RawAttendance")
                                    writer.save()
                                bio.seek(0)
                                st.download_button("📥 Download Weekly Report (Excel)", data=bio, file_name=f"weekly_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                else:
                    st.info("No students in this course yet.")
            else:
                st.info("No courses in selected department.")
        else:
            st.info("No departments in selected college.")
    else:
        st.info("No colleges in system.")

# ---------------------------
# PAGE: Admin
# ---------------------------
elif page == "Admin":
    st.header("⚙️ Admin")
    st.write("Database file:", DB_PATH, " — You can back it up or move it if needed.")
    if st.button("Initialize / Reset DB (ensure tables exist)"):
        init_db()
        st.success("DB initialized (tables ensured).")
    if Path(DB_PATH).exists():
        st.write("DB size:", f"{Path(DB_PATH).stat().st_size/1024:.1f} KB")
        with open(DB_PATH,"rb") as f:
            st.download_button("Download DB file (backup)", data=f, file_name="attendance.db", mime="application/octet-stream")
    else:
        st.info("DB file not found (it will be created on first run).")
