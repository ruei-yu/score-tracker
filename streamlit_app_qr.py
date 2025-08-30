import streamlit as st
import pandas as pd
import json, io
from datetime import date, datetime
from urllib.parse import quote, unquote
import qrcode

st.set_page_config(page_title="集點計分器 + 報到QR", page_icon="🔢", layout="wide")

# ---------- Helpers ----------
def load_config(file):
    try:
        return json.load(open(file, "r", encoding="utf-8"))
    except Exception:
        return {" scoring_items": [], "rewards": []}

def save_config(cfg, file):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def normalize_names(s: str):
    if not s:
        return []
    raw = (
        s.replace("、", ",").replace("，", ",")
         .replace("（", "(").replace("）", ")")
         .replace(" ", ",")
    )
    out = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if "(" in token and ")" in token:
            token = token.split("(")[0].strip()
        out.append(token)
    return [n for n in out if n]

def aggregate(df, points_map, rewards):
    if df.empty:
        return pd.DataFrame(columns=["participant", "總點數"])
    df = df.copy()
    df["points"] = df["category"].map(points_map).fillna(0).astype(int)
    summary = (
        df.pivot_table(index="participant", columns="category",
                       values="points", aggfunc="count", fill_value=0)
          .sort_index()
    )
    # 加總
    summary["總點數"] = 0
    for cat, pt in points_map.items():
        if cat in summary.columns:
            summary["總點數"] += summary[cat] * pt
    # 門檻
    thresholds = sorted([r["threshold"] for r in rewards])
    def reward_badge(x):
        gain = [t for t in thresholds if x >= t]
        return (max(gain) if gain else 0)
    summary["已達門檻"] = summary["總點數"].apply(reward_badge)
    return summary.reset_index().sort_values(["總點數","participant"], ascending=[False,True])

def save_events(df, path):
    df.to_csv(path, index=False, encoding="utf-8-sig")

def load_events(path):
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=["date","title","category","participant"])

# ---------- Public check-in via URL ----------
qp = st.query_params
mode = qp.get("mode", "")
event_param = qp.get("event", "")

if mode == "checkin":
    st.markdown("### ✅ 線上報到（公開頁）")
    data_file = st.text_input("資料儲存CSV路徑", value="events.csv", key="ci_datafile")
    events_df = load_events(data_file)

    # event info from URL
    title, category, target_date = "未命名活動", "活動護持（含宿訪）", date.today().isoformat()
    try:
        decoded = unquote(event_param)
        if decoded.strip().startswith("{"):
            o = json.loads(decoded)
            title = o.get("title", title)
            category = o.get("category", category)
            target_date = o.get("date", target_date)
        else:
            title = decoded or title
    except Exception:
        pass

    st.info(f"活動：**{title}**｜類別：**{category}**｜日期：{target_date}")

    # 多名同時報到
    names_input = st.text_area(
        "請輸入姓名（可用「、」「，」或空白分隔；可含括號註記）",
        key="ci_names",
        placeholder="例如：曉瑩、筱晴、崇萱（六） 佳宜 睿妤"
    )
    if st.button("送出報到", key="ci_submit"):
        names = normalize_names(names_input)
        if not names:
            st.error("請至少輸入一位姓名。")
        else:
            existing = set(
                events_df.loc[
                    (events_df["date"] == target_date) &
                    (events_df["title"] == title) &
                    (events_df["category"] == category),
                    "participant"
                ].astype(str).tolist()
            )
            to_add, skipped = [], []
            for n in names:
                if n in existing:
                    skipped.append(n)
                else:
                    to_add.append({
                        "date": target_date, "title": title,
                        "category": category, "participant": n
                    })
                    existing.add(n)
            if to_add:
                events_df = pd.concat([events_df, pd.DataFrame(to_add)], ignore_index=True)
                save_events(events_df, data_file)
                st.success(f"已報到 {len(to_add)} 人：{'、'.join([r['participant'] for r in to_add])}")
            if skipped:
                st.warning(f"以下人員已經報到過，已跳過：{'、'.join(skipped)}")
    st.stop()

# ---------- Admin UI ----------
st.title("1️⃣2️⃣3️⃣4️⃣  集點計分器 + 報到QR")

# Sidebar settings
st.sidebar.title("⚙️ 設定")
cfg_file = st.sidebar.text_input("設定檔路徑", value="points_config.json", key="cfg_path")
data_file = st.sidebar.text_input("資料儲存CSV路徑", value="events.csv", key="data_path")

if "config" not in st.session_state:
    st.session_state.config = load_config(cfg_file)
if "events" not in st.session_state:
    st.session_state.events = load_events(data_file)

config = st.session_state.config
scoring_items = config.get(" scoring_items", [])
rewards = config.get("rewards", [])
points_map = {i["category"]: int(i["points"]) for i in scoring_items}

# Sidebar editors
with st.sidebar.expander("➕ 編輯集點項目與點數", expanded=False):
    st.caption("新增或調整表格後點『儲存設定』。")
    items_df = pd.DataFrame(scoring_items) if scoring_items else pd.DataFrame(columns=["category","points"])
    edited = st.data_editor(items_df, num_rows="dynamic", use_container_width=True, key="items_editor")
    if st.button("💾 儲存設定（集點項目）", key="save_items"):
        config[" scoring_items"] = edited.dropna(subset=["category"]).to_dict(orient="records")
        st.session_state.config = config
        save_config(config, cfg_file)
        st.success("已儲存集點項目。")

with st.sidebar.expander("🎁 編輯獎勵門檻", expanded=False):
    rew_df = pd.DataFrame(rewards) if rewards else pd.DataFrame(columns=["threshold","reward"])
    rew_edit = st.data_editor(rew_df, num_rows="dynamic", use_container_width=True, key="rewards_editor")
    if st.button("💾 儲存設定（獎勵）", key="save_rewards"):
        config["rewards"] = [
            {"threshold": int(r["threshold"]), "reward": r["reward"]}
            for r in rew_edit.dropna(subset=["threshold","reward"]).to_dict(orient="records")
        ]
        st.session_state.config = config
        save_config(config, cfg_file)
        st.success("已儲存獎勵門檻。")

# ---------- Main Tabs ----------
tabs = st.tabs(["🟪 產生 QR", "📝 現場報到", "👤 個人明細", "🏆 排行榜", "📒 完整紀錄"])

# 1) 產生 QR
with tabs[0]:
    st.subheader("生成報到 QR Code")
    public_base = st.text_input("公開網址（本頁網址）", value="", key="qr_public_url")
    if public_base.endswith("/"):
        public_base = public_base[:-1]
    qr_title = st.text_input("活動標題", value="迎新晚會", key="qr_title")
    qr_category = st.selectbox("類別", list(points_map.keys()) or ["活動護持（含宿訪）"], key="qr_category")
    qr_date = st.date_input("活動日期", value=date.today(), key="qr_date")

    payload = json.dumps({"title": qr_title or qr_category,
                          "category": qr_category,
                          "date": qr_date.isoformat()}, ensure_ascii=False)
    encoded = quote(payload, safe="")
    if public_base:
        checkin_url = f"{public_base}/?mode=checkin&event={encoded}"
        st.write("**報到連結：**")
        st.code(checkin_url, language="text")
        img = qrcode.make(checkin_url)
        buf = io.BytesIO(); img.save(buf, format="PNG")
        st.image(buf.getvalue(), caption="請讓大家掃描此 QR 報到", width=260)
        st.download_button("⬇️ 下載 QR 圖片", data=buf.getvalue(),
                           file_name=f"checkin_qr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                           mime="image/png", key="qr_download")
    else:
        st.info("請貼上你的 .streamlit.app 網址（本頁網址）。")

# 2) 現場報到（管理者用）
with tabs[1]:
    st.subheader("現場快速報到（多名一起）")
    # 活動三要素
    on_title = st.text_input("活動標題", value="未命名活動", key="on_title")
    on_category = st.selectbox("類別", list(points_map.keys()) or ["活動護持（含宿訪）"], key="on_category")
    on_date = st.date_input("日期", value=date.today(), key="on_date")
    st.caption("提示：下方可一次輸入多位，以「、」「，」「空白」分隔，可含括號註記。")

    names_input = st.text_area("姓名清單", placeholder="曉瑩、筱晴（六） 佳宜 睿妤", key="on_names")
    if st.button("➕ 加入報到名單", key="on_add"):
        ev = st.session_state.events.copy()
        target_date = on_date.isoformat()
        names = normalize_names(names_input)
        if not names:
            st.warning("請至少輸入一位姓名。")
        else:
            existing = set(
                ev.loc[
                    (ev["date"] == target_date) &
                    (ev["title"] == on_title) &
                    (ev["category"] == on_category),
                    "participant"
                ].astype(str).tolist()
            )
            to_add, skipped = [], []
            for n in names:
                if n in existing:
                    skipped.append(n)
                else:
                    to_add.append({"date": target_date, "title": on_title,
                                   "category": on_category, "participant": n})
                    existing.add(n)
            if to_add:
                ev = pd.concat([ev, pd.DataFrame(to_add)], ignore_index=True)
                st.session_state.events = ev
                save_events(ev, data_file)
                st.success(f"已加入 {len(to_add)} 人：{'、'.join([r['participant'] for r in to_add])}")
            if skipped:
                st.warning(f"已跳過（重複）：{'、'.join(skipped)}")

# 3) 個人明細
with tabs[2]:
    st.subheader("個人參加明細")
    if st.session_state.events.empty:
        st.info("目前尚無活動紀錄。")
    else:
        c1, c2 = st.columns(2)
        with c1:
            person = st.selectbox("選擇參加者", 
                                  sorted(st.session_state.events["participant"].unique()),
                                  key="detail_person")
        with c2:
            only_cat = st.multiselect("篩選類別（可多選）",
                                      options=sorted(st.session_state.events["category"].unique()),
                                      default=None, key="detail_cats")
        dfp = st.session_state.events.query("participant == @person").copy()
        if only_cat:
            dfp = dfp[dfp["category"].isin(only_cat)]
        st.dataframe(dfp[["date","title","category"]].sort_values("date"),
                     use_container_width=True, height=350)
        st.download_button("⬇️ 下載此人明細 CSV",
                           data=dfp.to_csv(index=False, encoding="utf-8-sig"),
                           file_name=f"{person}_records.csv", mime="text/csv",
                           key="dl_person")

    st.markdown("---")
    st.subheader("📆 依日期查看參與者")
    if st.session_state.events.empty:
        st.info("目前尚無活動紀錄。")
    else:
        sel_date = st.date_input("選擇日期", value=date.today(), key="bydate_date")
        sel_date_str = sel_date.isoformat()
        day_df = st.session_state.events[st.session_state.events["date"].astype(str) == sel_date_str].copy()
        if day_df.empty:
            st.info(f"{sel_date_str} 沒有任何紀錄。")
        else:
            cat_options = sorted(day_df["category"].astype(str).unique())
            sel_cats = st.multiselect("篩選類別（可多選）", options=cat_options, default=cat_options, key="bydate_cats")
            show_df = day_df[day_df["category"].isin(sel_cats)].copy()
            names = sorted(show_df["participant"].astype(str).unique())
            st.write(f"**共 {len(names)} 人**：", "、".join(names) if names else "（無）")
            st.dataframe(show_df[["participant","title","category"]]
                         .sort_values(["category","participant"]), use_container_width=True, height=300)
            st.download_button("⬇️ 下載當日明細 CSV",
                               data=show_df.to_csv(index=False, encoding="utf-8-sig"),
                               file_name=f"events_{sel_date_str}.csv", mime="text/csv",
                               key="bydate_download")

# 4) 排行榜
with tabs[3]:
    st.subheader("排行榜（依總點數）")
    summary = aggregate(st.session_state.events, points_map, rewards)
    st.dataframe(summary, use_container_width=True, height=520)

# 5) 完整紀錄
with tabs[4]:
    st.subheader("完整紀錄（可編輯）")
    st.caption("欄位：date, title, category, participant")
    edited = st.data_editor(st.session_state.events, num_rows="dynamic",
                            use_container_width=True, key="full_editor")
    st.session_state.events = edited
    save_events(edited, data_file)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("⬇️ 下載 CSV",
                           data=edited.to_csv(index=False, encoding="utf-8-sig"),
                           file_name="events_export.csv", mime="text/csv",
                           key="full_download")
    with c2:
        if st.button("🗄️ 歸檔並清空", key="full_archive"):
            backup_name = f"events_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            edited.to_csv(backup_name, index=False, encoding="utf-8-sig")
            st.session_state.events = edited.iloc[0:0]
            save_events(st.session_state.events, data_file)
            st.success(f"已備份到 {backup_name} 並清空。")
    with c3:
        if st.button("♻️ 只清空（不備份）", key="full_clear"):
            st.session_state.events = edited.iloc[0:0]
            save_events(st.session_state.events, data_file)
            st.success("已清空所有資料（未備份）。")
