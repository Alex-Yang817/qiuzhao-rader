#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋招雷达 · 自动采集器（多源版）
====================================================
数据源（均为政府官方网站、服务端渲染、可稳定抓取）：
  1) 国务院国资委官网「招聘」栏目   —— 中央企业招聘公告（含央企所属单位）
     http://www.sasac.gov.cn/n2588035/n2588325/n2588350/index.html
  2) 上海市国资委官网「国企招聘」栏目 —— 上海市属/区属国企招聘公告
     https://www.gzw.sh.gov.cn/shgzw_xxgk_cqzp/index.html

输出：
  data/announcements.json   官方公告动态流(多源合并, 按 url 去重, 记录 first_seen 与 channel)
  data/last_run.json        最近一次运行摘要(前端据此显示"上次自动采集")

边界（如实说明）：
  - 本采集器自动完成「官方公告动态」的例行抓取与存档（标题/原文链接/日期/来源）。
  - 岗位结构化字段(报名截止/专业标签/港澳适用性等)仍需人工按官方公告核实,
    维护在 data/jobs.json（种子数据为 2026-09-05 人工核实版本）。
  - 各集团自建招聘系统/第三方平台(智联等)及国聘(iguopin)为 JS 应用或带反爬，
    服务器端直抓不可靠，不作自动源；可作为人工补充查询渠道。

仅使用 Python 标准库。用法：python3 scraper/main.py [--out data]
"""
import argparse
import json
import os
import posixpath
import re
import sys
import urllib.request
import ssl
from datetime import datetime, date

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

# ---------------- 源定义 ----------------
# mode="gov": 链接为 ../../../ 相对栏目目录（国资委官网）
# mode="root": 链接为 /xxx 根相对（上海国资委官网）
SOURCES = [
    {
        "key": "sasac",
        "name": "国务院国资委官网·招聘栏目",
        "channel": "央企·国资委官网",
        "base": "http://www.sasac.gov.cn",
        "dir": "/n2588035/n2588325/n2588350",
        "mode": "gov",
        "pages": 1,
        # 条目: <li> <a href=... title=标题>标题</a><span>[YYYY-MM-DD]</span></li>
        "regex": re.compile(
            r'<li>\s*<a href="([^"]+)"[^>]*title="([^"]+)"[^>]*>.*?'
            r'<span>\[(\d{4}-\d{2}-\d{2})\]</span>\s*</li>', re.S),
        "order": (1, 2, 3),  # (href, title, date) 在 match 中的 group 下标(从1起)
    },
    {
        "key": "gzsh",
        "name": "上海市国资委官网·国企招聘栏目",
        "channel": "上海国企·上海国资委官网",
        "base": "https://www.gzw.sh.gov.cn",
        "dir": "/shgzw_xxgk_cqzp",
        "mode": "root",
        "pages": 1,
        # 条目: <li class=localbox><span class=localbox>YYYY-MM-DD</span><a href=... title=标题>（注意 <a 与 href 间可能跨行）
        "regex": re.compile(
            r'<li[^>]*>\s*<span[^>]*>(\d{4}-\d{2}-\d{2})</span>\s*'
            r'<a\s+href="([^"]+)"[^>]*title="([^"]+)"', re.S),
        "order": (2, 3, 1),  # (href, title, date) 对应 groups: date=1,href=2,title=3
    },
]

KIND_HIT = ("校园招聘", "校招", "秋招", "应届", "毕业生", "届")


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as r:
        return r.read().decode("utf-8", "ignore")


def resolve(src: dict, href: str) -> str:
    if href.startswith("http"):
        return href
    if src["mode"] == "root":
        p = href if href.startswith("/") else "/" + href
        return src["base"] + p
    # gov 模式：../../../ 相对栏目目录
    p = posixpath.normpath(posixpath.join(src["dir"], href))
    return src["base"] + "/" + p.lstrip("/")


def guess_org(title: str) -> str:
    m = re.search(r"(20\d{2}届|20\d{2}年|校招|校园|秋季|招聘|社会|公开|毕业生)", title)
    org = title[:m.start()] if m else title
    org = re.sub(r"^[·\s:：\-—]+", "", org).strip(" ·—:：　")
    org = re.sub(r"20\d{2}$", "", org).strip(" ·—:：　")  # 去除截断后残留的"2027"式年份
    return org or title[:16]


def kind_of(title: str) -> str:
    return "campus" if any(k in title for k in KIND_HIT) else "other"


def crawl_source(src: dict) -> list:
    """抓单个源第1页；返回规范条目列表 [{title,url,org,date,kind}]"""
    out = []
    url = f"{src['base']}{src['dir']}/index.html"
    try:
        html = fetch(url)
    except Exception as e:
        raise RuntimeError(f"抓取失败 {src['name']}: {e}")
    hi, ti, di = src["order"]
    for m in src["regex"].finditer(html):
        href, title, dt = m.group(hi), m.group(ti), m.group(di)
        out.append({
            "title": title.strip(),
            "url": resolve(src, href),
            "org": guess_org(title),
            "date": dt,
            "kind": kind_of(title),
            "channel": src["channel"],
        })
    return out


def merge(old_items: list, fresh: list, today: str) -> tuple:
    by_url = {it["url"]: it for it in old_items}
    new_count = 0
    for it in fresh:
        key = it["url"]
        if key in by_url:
            old = by_url[key]
            old["n_seen"] = old.get("n_seen", 1) + 1
            old["last_seen"] = today
            if old.get("title") != it["title"] or old.get("date") != it["date"]:
                old["title"], old["date"] = it["title"], it["date"]
        else:
            it["first_seen"] = today
            it["n_seen"] = 1
            it["last_seen"] = today
            by_url[key] = it
            new_count += 1
    items = sorted(by_url.values(), key=lambda x: x.get("date", ""), reverse=True)
    # 旧数据无 channel 字段的，按国资委栏目来源补齐（旧数据均来自该源）
    for it in items:
        it.setdefault("channel", "央企·国资委官网")
    return items[:160], new_count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    ann_path = os.path.join(args.out, "announcements.json")
    run_path = os.path.join(args.out, "last_run.json")

    old_items = []
    if os.path.exists(ann_path):
        try:
            old_items = json.load(open(ann_path, encoding="utf-8")).get("items", [])
        except Exception:
            old_items = []

    today = date.today().isoformat()
    all_fresh, errors, src_stats = [], [], []
    for src in SOURCES:
        try:
            items = crawl_source(src)
            all_fresh.extend(items)
            src_stats.append({"name": src["name"], "ok": True, "got": len(items)})
            print(f"[ok] {src['name']}: {len(items)} 条")
        except Exception as e:
            errors.append(str(e))
            src_stats.append({"name": src["name"], "ok": False, "got": 0})
            print(f"[error] {e}", file=sys.stderr)

    items, new_count = merge(old_items, all_fresh, today)
    campus = sum(1 for it in items if it.get("kind") == "campus")

    payload = {
        "source": " / ".join(s["name"] for s in SOURCES),
        "sources": [s["name"] for s in SOURCES],
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated_date": today,
        "campus_count": campus,
        "items": items,
    }
    with open(ann_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    run = {
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "new_count": new_count,
        "total_items": len(items),
        "campus_items": campus,
        "sources": src_stats,
        "errors": errors,
    }
    with open(run_path, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=1)

    print(f"[ok] 合并完成: 本轮新增 {new_count} 条, 当前共 {len(items)} 条(校招类 {campus})")


if __name__ == "__main__":
    main()
