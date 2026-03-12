"""
Hikvision qurilma (kirish nazorati / tabel) bilan ishlash.
ISAPI, Digest auth. Qurilma: https://192.168.1.199/doc/index.html
"""
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
import xml.etree.ElementTree as ET

try:
    import requests
    from requests.auth import HTTPDigestAuth
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    requests = None
    HTTPDigestAuth = None


class HikvisionAPI:
    """Hikvision ISAPI orqali qurilma bilan muloqot."""
    
    def __init__(
        self,
        host: str = "192.168.1.199",
        port: int = 443,
        username: str = "admin",
        password: str = "",
        use_https: bool = True,
    ):
        self.host = host.rstrip("/")
        self.port = port
        self.username = username
        self.password = password
        proto = "https" if use_https else "http"
        self.base_url = f"{proto}://{host}:{port}"
        self._last_status: Optional[int] = None
        self._last_error: Optional[str] = None
        self._session = None
    
    def _get_session(self):
        if requests is None:
            raise RuntimeError("requests kutubxonasi o'rnatilmagan: pip install requests")
        if self._session is None:
            self._session = requests.Session()
            self._session.auth = HTTPDigestAuth(self.username, self.password)
            self._session.verify = False
            # Content-Type har bir so'rovda beriladi (JSON yoki XML)
        return self._session
    
    def test_connection(self) -> bool:
        """Qurilma javob beradimi tekshirish."""
        self._last_status = None
        self._last_error = None
        try:
            r = self._get_session().get(
                f"{self.base_url}/ISAPI/System/deviceInfo",
                timeout=10,
            )
            self._last_status = r.status_code
            if r.status_code == 200:
                return True
            if r.status_code in (401, 403):
                self._last_error = f"Auth: {r.status_code}"
            return False
        except requests.exceptions.SSLError as e:
            self._last_error = str(e)
            return False
        except requests.exceptions.ConnectionError as e:
            self._last_error = str(e)
            return False
        except Exception as e:
            self._last_error = str(e)
            return False
    
    def _parse_userinfo_xml(self, content: bytes) -> List[Dict[str, Any]]:
        """XML javobdan UserInfo yoki shaxs yozuvlarini ajratib olish."""
        out: List[Dict[str, Any]] = []
        try:
            root = ET.fromstring(content)
            for elem in root.iter():
                tag_local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag_local not in ("UserInfo", "User", "Person", "EmployeeInfo"):
                    continue
                rec = {}
                for c in elem:
                    child_tag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
                    val = (c.text or "").strip()
                    if child_tag in ("employeeNo", "employeeNoString", "id"):
                        rec["employeeNo"] = val
                    elif child_tag in ("name", "personName", "userName"):
                        rec["name"] = val
                    elif child_tag == "department":
                        rec["department"] = val
                if rec.get("employeeNo") or rec.get("name"):
                    if "employeeNo" not in rec:
                        rec["employeeNo"] = rec.get("name", "") or str(len(out) + 1)
                    out.append(rec)
        except ET.ParseError:
            pass
        return out

    def get_person_list(self) -> List[Dict[str, Any]]:
        """
        Qurilmadagi shaxslar ro'yxatini olish.
        Avval Telegram botda ishlatiladigan JSON format (UserInfo/Search?format=json) sinanadi,
        keyin XML va boshqa endpoint'lar.
        """
        self._last_status = None
        self._last_error = None
        out: List[Dict[str, Any]] = []

        # 1) Bot formatida: POST .../UserInfo/Search?format=json, JSON body (Hikvision ISAPI standarti)
        url_json = f"{self.base_url}/ISAPI/AccessControl/UserInfo/Search?format=json"
        payload = {
            "UserInfoSearchCond": {
                "searchID": "1",
                "searchResultPosition": 0,
                "maxResults": 1000,
            }
        }
        try:
            r = self._get_session().post(url_json, json=payload, timeout=30)
            self._last_status = r.status_code
            if r.status_code == 200:
                data = r.json()
                # Javob: UserInfoSearch -> UserInfo (massiv; bitta bo'lsa ham object qaytishi mumkin)
                user_info_search = data.get("UserInfoSearch") if isinstance(data, dict) else {}
                if isinstance(user_info_search, dict):
                    users = user_info_search.get("UserInfo") or user_info_search.get("UserInfoList") or []
                else:
                    users = []
                if not isinstance(users, list):
                    users = [users] if users else []
                for i, u in enumerate(users):
                    if not isinstance(u, dict):
                        continue
                    emp_no = str(u.get("employeeNo") or u.get("employeeNoString") or u.get("id") or (i + 1))
                    name = (u.get("name") or u.get("personName") or "Noma'lum").strip()
                    out.append({
                        "employeeNo": emp_no,
                        "name": name,
                        "department": (u.get("department") or "").strip(),
                    })
                if out:
                    return out
        except Exception as e:
            self._last_error = str(e)

        # 2) XML format (eski endpoint)
        search_body = """<?xml version="1.0" encoding="UTF-8"?>
<UserInfoSearch>
  <searchID>1</searchID>
  <searchResultPosition>0</searchResultPosition>
  <maxResults>500</maxResults>
</UserInfoSearch>"""
        try:
            url_xml = f"{self.base_url}/ISAPI/AccessControl/UserInfo/Search"
            r = self._get_session().post(
                url_xml,
                data=search_body,
                headers={"Content-Type": "application/xml"},
                timeout=15,
            )
            self._last_status = r.status_code
            if r.status_code == 200:
                ct = (r.headers.get("content-type") or "").lower()
                if "json" in ct:
                    data = r.json()
                    lst = (data.get("UserInfoSearch") or {}).get("UserInfo") or data.get("UserInfo") or data.get("Person") or []
                    if not isinstance(lst, list):
                        lst = [lst] if lst else []
                    for i, p in enumerate(lst):
                        if isinstance(p, dict):
                            out.append({
                                "employeeNo": str(p.get("employeeNo") or p.get("id") or (i + 1)),
                                "name": (p.get("name") or p.get("personName") or "").strip(),
                                "department": (p.get("department") or "").strip(),
                            })
                else:
                    out = self._parse_userinfo_xml(r.content)
                if out:
                    return out
        except Exception as e:
            self._last_error = str(e)

        # 3) Qo'shimcha endpoint'lar
        for url in [
            f"{self.base_url}/ISAPI/AccessControl/UserInfo/Record?format=json",
            f"{self.base_url}/ISAPI/Intelligent/peopleManagement/person?format=json",
        ]:
            if out:
                break
            try:
                r = self._get_session().get(url, timeout=15)
                self._last_status = r.status_code
                if r.status_code != 200:
                    continue
                data = r.json()
                lst = (data.get("UserInfoSearch") or {}).get("UserInfo") or data.get("UserInfo") or data.get("Person") or (data if isinstance(data, list) else [])
                if not isinstance(lst, list):
                    lst = [lst] if lst else []
                for i, p in enumerate(lst):
                    if isinstance(p, dict):
                        out.append({
                            "employeeNo": str(p.get("employeeNo") or p.get("id") or (i + 1)),
                            "name": (p.get("name") or p.get("personName") or "").strip(),
                            "department": (p.get("department") or "").strip(),
                        })
                if out:
                    return out
            except Exception:
                continue
        return out

    def _parse_events_from_response(self, data: Any) -> List[Dict[str, Any]]:
        """JSON javobdan hodisalar ro'yxatini ajratib oladi (turli Hikvision firmware formatlari)."""
        out: List[Dict[str, Any]] = []
        if not isinstance(data, dict):
            return out
        acs = data.get("AcsEvent") or data.get("acsEvent")
        if isinstance(acs, list):
            info_list = acs
        elif isinstance(acs, dict):
            info_list = acs.get("InfoList") or acs.get("infoList") or acs.get("MatchList") or []
        else:
            info_list = data.get("InfoList") or data.get("infoList") or data.get("MatchList") or []
        if not isinstance(info_list, list):
            info_list = [info_list] if info_list else []
        for e in info_list:
            if not isinstance(e, dict):
                continue
            emp_no = (e.get("employeeNoString") or e.get("employeeNo") or "").strip() or str(e.get("id", "")).strip()
            if not emp_no:
                continue
            rec = {
                "employeeNo": emp_no,
                "time": e.get("time") or e.get("dateTime") or e.get("eventTime") or "",
                "name": e.get("name") or e.get("personName") or "Noma'lum",
            }
            for k, v in e.items():
                if v and isinstance(v, str) and any(x in k.lower() for x in ("pic", "photo", "image", "snap", "uri")):
                    if "pic" in k.lower() or "photo" in k.lower() or "image" in k.lower() or "snap" in k.lower():
                        rec[k] = v
            out.append(rec)
        return out

    def get_events(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """
        Berilgan sana oralig'ida kirish/chiqish hodisalarini olish.
        Bir nechta vaqt formati sinanadi (qurilma firmwaresiga qarab).
        """
        out: List[Dict[str, Any]] = []
        max_results = 100
        max_position = 20000
        time_formats = [
            (start_date.strftime("%Y-%m-%d") + " 00:00:00", end_date.strftime("%Y-%m-%d") + " 23:59:59"),
            (start_date.strftime("%Y-%m-%d") + "T00:00:00", end_date.strftime("%Y-%m-%d") + "T23:59:59"),
            (start_date.strftime("%Y-%m-%d") + "T00:00:00+05:00", end_date.strftime("%Y-%m-%d") + "T23:59:59+05:00"),
        ]
        for start_str, end_str in time_formats:
            if out:
                break
            position = 0
            while True:
                try:
                    url = f"{self.base_url}/ISAPI/AccessControl/AcsEvent?format=json"
                    payload = {
                        "AcsEventCond": {
                            "searchID": "1",
                            "searchResultPosition": position,
                            "maxResults": max_results,
                            "major": 0,
                            "minor": 0,
                            "startTime": start_str,
                            "endTime": end_str,
                        }
                    }
                    r = self._get_session().post(url, json=payload, timeout=60)
                    if r.status_code != 200:
                        self._last_status = r.status_code
                        break
                    data = r.json()
                    chunk = self._parse_events_from_response(data)
                    out.extend(chunk)
                    acs = (data.get("AcsEvent") or data.get("acsEvent")) if isinstance(data, dict) else None
                    acs_dict = acs if isinstance(acs, dict) else {}
                    if acs_dict.get("responseStatusStrg") != "MORE":
                        break
                    position += max_results
                    if position >= max_position:
                        break
                except Exception:
                    break
        return out

    def get_event_image_url(self, event: Dict[str, Any]) -> Optional[str]:
        """Hodisa rasmi URI/pictureURL ni qaytaradi (agar bor bo'lsa)."""
        for key in ("picUri", "pictureURL", "pictureUri", "photoURL", "eventPictureUri", "snapshotURL"):
            val = event.get(key)
            if val and isinstance(val, str) and val.strip():
                return val.strip()
        return None

    def download_event_image(self, uri: str) -> Optional[bytes]:
        """Hodisa rasmini yuklab bytes qaytaradi. uri nisbiy (/pic/...) yoki to'liq bo'lishi mumkin."""
        if not uri:
            return None
        try:
            if uri.startswith("http://") or uri.startswith("https://"):
                url = uri
            else:
                url = self.base_url.rstrip("/") + ("/" if not uri.startswith("/") else "") + uri
            r = self._get_session().get(url, timeout=15)
            if r.status_code == 200 and r.content:
                return r.content
        except Exception:
            pass
        return None


def sync_hikvision_attendance(
    hikvision_host: str,
    hikvision_port: int,
    hikvision_username: str,
    hikvision_password: str,
    start_date: date,
    end_date: date,
    db_session: Any,
) -> Dict[str, Any]:
    """
    Hikvision'dan berilgan sana oralig'idagi kirish/chiqish hodisalarini yuklab,
    attendances jadvaliga yozish. Xodimlar employeeNo/hikvision_id/code orqali moslashtiriladi.
    """
    from app.models.database import Attendance, Employee
    
    result: Dict[str, Any] = {"success": False, "imported": 0, "errors": [], "events_count": 0, "matched_count": 0}
    if requests is None:
        result["errors"].append("requests kutubxonasi o'rnatilmagan.")
        return result
    
    try:
        api = HikvisionAPI(
            host=hikvision_host,
            port=hikvision_port,
            username=hikvision_username,
            password=hikvision_password,
        )
        if not api.test_connection():
            result["errors"].append(api._last_error or "Qurilma bilan bog'lanib bo'lmadi.")
            return result
        
        # Hodisalarni POST AcsEvent orqali olish (bot formatida, birinchi/oxirgi vaqt hisoblash uchun)
        events = api.get_events(start_date, end_date)
        result["events_count"] = len(events)

        if not events:
            result["errors"].append("Hikvision qurilmasidan shu sana uchun hodisa qaytmadi. IP/parol va sana to'g'riligini tekshiring.")

        # employeeNo -> employee_id (barcha xodimlar, jumladan Hikvision'dan import qilingan is_active=False)
        employee_by_no: Dict[str, int] = {}
        for emp in db_session.query(Employee).all():
            for key in (getattr(emp, "hikvision_id", None), getattr(emp, "code", None)):
                if key:
                    employee_by_no[str(key).strip()] = emp.id
        
        # (employee_id, sana) bo'yicha vaqtlar va hodisalarni yig'ish (rasm uchun birinchi hodisani saqlaymiz)
        from collections import defaultdict
        by_emp_date: Dict[tuple, List[tuple]] = defaultdict(list)  # (dt, ev)
        for ev in events:
            emp_no = ev.get("employeeNo") or ""
            emp_id = employee_by_no.get(emp_no)
            if not emp_id:
                continue
            ev_time = ev.get("time") or ""
            if not ev_time:
                continue
            try:
                if "T" in ev_time:
                    dt = datetime.fromisoformat(ev_time.replace("Z", "+00:00"))
                else:
                    dt = datetime.strptime(ev_time[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            ev_date = dt.date()
            if not (start_date <= ev_date <= end_date):
                continue
            by_emp_date[(emp_id, ev_date)].append((dt, ev))
        
        result["matched_count"] = len(by_emp_date)
        if result["events_count"] > 0 and result["matched_count"] == 0:
            result["errors"].append(
                "Hikvisiondan %s ta hodisa keldi, lekin hech bir xodim ro'yxatga mos emas. "
                "Xodimlarda «Hikvision ID» yoki «Kod» maydonini qurilmadagi raqamga moslang." % result["events_count"]
            )
        unique_dates = sorted(set(d for (_, d) in by_emp_date))
        result["days_with_data"] = unique_dates
        result["days_count"] = len(unique_dates)
        
        import os
        snapshot_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "app", "static", "attendance_snapshots")
        os.makedirs(snapshot_dir, exist_ok=True)
        
        for (emp_id, ev_date), time_ev_list in by_emp_date.items():
            try:
                if not time_ev_list:
                    continue
                first_in = min(dt for dt, _ in time_ev_list)
                last_out = max(dt for dt, _ in time_ev_list)
                first_ev = next((ev for dt, ev in time_ev_list if dt == first_in), time_ev_list[0][1])
                hours_worked = 0.0
                if first_in and last_out and last_out > first_in:
                    hours_worked = round((last_out - first_in).total_seconds() / 3600.0, 2)
                att = (
                    db_session.query(Attendance)
                    .filter(Attendance.employee_id == emp_id, Attendance.date == ev_date)
                    .first()
                )
                if not att:
                    att = Attendance(
                        employee_id=emp_id,
                        date=ev_date,
                        check_in=first_in,
                        check_out=last_out,
                        hours_worked=hours_worked,
                        status="present",
                    )
                    db_session.add(att)
                    result["imported"] += 1
                else:
                    att.check_in = first_in
                    att.check_out = last_out
                    att.hours_worked = hours_worked
                image_url = api.get_event_image_url(first_ev)
                if image_url:
                    try:
                        img_data = api.download_event_image(image_url)
                        if img_data:
                            ext = ".jpg" if img_data[:3] == b"\xff\xd8\xff" else ".png"
                            fn = f"{ev_date.strftime('%Y-%m-%d')}_{emp_id}{ext}"
                            path = os.path.join(snapshot_dir, fn)
                            with open(path, "wb") as f:
                                f.write(img_data)
                            att.event_snapshot_path = f"attendance_snapshots/{fn}"
                    except Exception:
                        pass
                db_session.commit()
            except Exception as e:
                result["errors"].append(str(e)[:100])
                db_session.rollback()
        
        result["success"] = True
    except Exception as e:
        result["errors"].append(str(e))
    
    return result


def import_employees_from_hikvision(
    hikvision_host: str,
    hikvision_port: int,
    hikvision_username: str,
    hikvision_password: str,
    db_session: Any,
    employee_nos: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Hikvision qurilmasidan shaxslar ro'yxatini olib, Employee jadvaliga qo'shadi yoki yangilaydi.
    employee_nos berilsa faqat shu Kod/ID dagi shaxslar yuklanadi; bo'lmasa hammasi.
    """
    from app.models.database import Employee

    result: Dict[str, Any] = {"success": False, "imported": 0, "updated": 0, "errors": []}
    if requests is None:
        result["errors"].append("requests kutubxonasi o'rnatilmagan.")
        return result

    try:
        api = HikvisionAPI(
            host=hikvision_host,
            port=hikvision_port,
            username=hikvision_username,
            password=hikvision_password,
        )
        if not api.test_connection():
            result["errors"].append(api._last_error or "Qurilma bilan bog'lanib bo'lmadi.")
            return result

        persons = api.get_person_list()
        if not persons:
            result["errors"].append("Qurilmada hech qanday shaxs topilmadi.")
            result["success"] = True
            return result

        allowed_set = None
        if employee_nos:
            allowed_set = {str(x).strip() for x in employee_nos if x and str(x).strip()}

        for p in persons:
            try:
                emp_no = (p.get("employeeNo") or "").strip()
                name = (p.get("name") or "").strip()
                department = (p.get("department") or "").strip()
                if not emp_no and not name:
                    continue
                if allowed_set is not None:
                    key = emp_no or name
                    if key not in allowed_set and name not in allowed_set:
                        continue
                code = (emp_no or "").strip() or ("HV-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + str(result["imported"] + result["updated"] + 1))
                employee = db_session.query(Employee).filter(Employee.code == code).first()
                if not employee and emp_no:
                    employee = db_session.query(Employee).filter(Employee.hikvision_id == emp_no).first()
                if employee:
                    employee.full_name = name or employee.full_name
                    employee.hikvision_id = emp_no or employee.hikvision_id
                    if department:
                        employee.department = department
                    result["updated"] += 1
                else:
                    new_emp = Employee(
                        code=code,
                        full_name=name or "Noma'lum",
                        hikvision_id=emp_no or None,
                        department=department or None,
                    )
                    db_session.add(new_emp)
                    result["imported"] += 1
                db_session.commit()
            except Exception as e:
                result["errors"].append(f"{emp_no or name}: {str(e)[:80]}")
                db_session.rollback()
        result["success"] = True
    except Exception as e:
        result["errors"].append(str(e))
    return result
