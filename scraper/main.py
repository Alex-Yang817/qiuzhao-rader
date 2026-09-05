#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋招雷达 · 自动采集器
====================================================
数据源(官方)：国务院国资委官网「招聘」栏目
  http://www.sasac.gov.cn/n2588035/n2588325/n2588350/index.html
  国资委官网是中央企业公开招聘信息的权威集中发布出口(服务端渲染、无强反爬)，
  可稳定抓取每条公告的【标题 / 原文链接 / 发布日期】。

输出：
  site/data/announcements.json   官方公告动态流(按 url 去重合并, 记录 first_seen)
  site/data/last_run.json        最近一次运行摘要(前端据此显示"上次自动采集"时间)

说明(诚实边界)：
  - 本采集器自动完成的是「官方公告动态」的例行抓取与存档；
  - 岗位结构化字段(报名截止/专业标签/港澳适用性等)仍需人工按官方公告核实,
    维护在 site/data/jobs.json(种子数据为 2026-09-05 人工核实版本)。
  - 各家官网(国家电网/中移动/国聘等)为动态页面或带 WAF(如电信412)，
    服务器端直接抓取不可靠，故不作主力源；本栏目已覆盖国资委下属央企招聘公告。

仅使用 Python 标准库，便于在 GitHub Actions / 任意机器直接运行。
用法：python3 scraper/main.py [--pages 3] [--out site/data]
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

BASE = "http://www.sasac.gov.cn"
LIST_DIR = "/n2588035/n2588325/n2588350"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

ITEM_RE = re.compile(
    r'<li>\s*<a href="([^"]+)"[^>]*title="([^"]+)"[^>]*>.*?'
    r'<span>\[(\d{4}-\d{2}-\d{2})\]</span>\s*</li>', re.S)


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as r:
        return r.read().decode("utf-8", "ignore")


def resolve(href: str) -> str:
    """把栏目页里的相对链接(如 ../../../n2588xxx/c1/content.html)拼成绝对URL"""
    if href.startswith("http"):
        return href
    p = posixpath.normpath(posixpath.join(LIST_DIR, href))
    if p.startswith("//"):
        p = "/" + p.lstrip("/")
    return BASE + "/" + p.lstrip("/")


def guess_org(title: str) -> str:
    """从公告标题启发式切出企业/单位名(如『中国电信集团2027年度校园招聘全面启动』→中国电信集团)"""
    m = re.search(r"(20\d{2}届|20\d{2}年|校招|校园|秋季|招聘|社会|公开|毕业生)", title)
    org = title[:m.start()] if m else title
    org = re.sub(r"^[·\s:：\-—]+", "", org).strip(" ·—:：　")
    return org or title[:16]


def kind_of(title: str) -> str:
    t = title
    if any(k in t for k in ("校园招聘", "校招", "秋招", "应届", "毕业生", "届")):
        return "campus"
    return "other"


def today_str() -> str:
    return date.today().isoformat()


def crawl(pages: int) -> list:
    """抓取栏目第1页及后续分页(命名 index.html / index_1.html ...)，按出现顺序去重返回条目"""
    seen = set()
    out = []
    for i in range(pages):
        name = "index.html" if i == 0 else f"index_{i}.html"
        url = f"{BASE}{LIST_DIR}/{name}"
        try:
            html = fetch(url)
        except Exception as e:
            print(f"[warn] 抓取失败 {url}: {e}", file=sys.stderr)
            break
        items = ITEM_RE.findall(html)
        if not items:
            print(f"[info] {url} 无更多条目", file=sys.stderr)
            break
        new = 0
        for href, title, dt in items:
            full = resolve(href)
            if full in seen:
                continue
            seen.add(full)
            out.append({"title": title.strip(), "url": full,
                        "org": guess_org(title), "date": dt,
                        "kind": kind_of(title)})
            new += 1
        print(f"[info] 第{i+1}页: 新增{new}/{len(items)}条")
    return out


def merge(old_items: list, fresh: list, today: str) -> tuple:
    """以 url 为键合并：返回(合并后items, 新增条数)"""
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
    return items[:120], new_count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--out", default=os.path.join("site", "data"))
    args = ap.parse_args()

    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    ann_path = os.path.join(out_dir, "announcements.json")
    run_path = os.path.join(out_dir, "last_run.json")

    old_items = []
    if os.path.exists(ann_path):
        try:
            old_items = json.load(open(ann_path, encoding="utf-8")).get("items", [])
        except Exception:
            old_items = []

    today = today_str()
    errors = []
    fresh = []
    try:
        fresh = crawl(args.pages)
    except Exception as e:  # 顶层兜底：主源整体失败时保留旧数据并记录
        errors.append(str(e))
        print(f"[error] 主源抓取失败: {e}", file=sys.stderr)

    items, new_count = merge(old_items, fresh, today)
    campus = sum(1 for it in items if it.get("kind") == "campus")

    payload = {
        "source": "国务院国资委官网·央企招聘栏目(官方)",
        "source_url": f"{BASE}{LIST_DIR}/index.html",
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
        "errors": errors,
        "source_url": payload["source_url"],
    }
    with open(run_path, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=1)

    print(f"[ok] 采集完成: 本轮新增 {new_count} 条, 当前共 {len(items)} 条(校招类 {campus})")


if __name__ == "__main__":
    main()
