#!/bin/bash
# HyperDB Download Monitor — runs every 30min until splits+dividends are done

cd /Users/tomschoen/Desktop/HyperDB
LOG_SPLITS="/private/tmp/claude-501/-Users-tomschoen/83bae290-610c-4cdd-86a1-739774897e8f/tasks/b6whoojb0.output"

while true; do
    echo ""
    echo "=========================================="
    echo "  HyperDB Status — $(date '+%Y-%m-%d %H:%M')"
    echo "=========================================="

    # Check if splits is running
    if pgrep -f "download splits" > /dev/null 2>&1; then
        PROGRESS=$(tail -c 200 "$LOG_SPLITS" 2>/dev/null | grep -oE '[0-9]+/145072' | tail -1)
        PCT=$(tail -c 200 "$LOG_SPLITS" 2>/dev/null | grep -oE '[0-9]+%' | tail -1)
        ETA=$(tail -c 200 "$LOG_SPLITS" 2>/dev/null | grep -oE '[0-9]+:[0-9]+:[0-9]+<[0-9:]+' | tail -1 | sed 's/.*<//')
        echo "  Splits:    🔄 $PCT ($PROGRESS) — ETA: $ETA"
        echo "  Dividends: ⏳ Wartet auf Splits"
    elif pgrep -f "download dividends" > /dev/null 2>&1; then
        DIV_LOG=$(ls -t /private/tmp/claude-501/-Users-tomschoen/*/tasks/*.output 2>/dev/null | head -1)
        PROGRESS=$(tail -c 200 "$DIV_LOG" 2>/dev/null | grep -oE '[0-9]+/145072' | tail -1)
        PCT=$(tail -c 200 "$DIV_LOG" 2>/dev/null | grep -oE '[0-9]+%' | tail -1)
        ETA=$(tail -c 200 "$DIV_LOG" 2>/dev/null | grep -oE '[0-9]+:[0-9]+:[0-9]+<[0-9:]+' | tail -1 | sed 's/.*<//')
        echo "  Splits:    ✅ Fertig"
        echo "  Dividends: 🔄 $PCT ($PROGRESS) — ETA: $ETA"
    else
        # Nothing running — check if splits finished, start dividends
        if [ -f "$LOG_SPLITS" ] && ! pgrep -f "download dividends" > /dev/null 2>&1; then
            # Check if dividends already completed
            DIVS_DONE=$(.venv/bin/python -c "
import duckdb
conn = duckdb.connect('data/hyperdb.duckdb', read_only=True, config={'threads':'1','memory_limit':'1GB'})
cnt = conn.execute(\"SELECT COUNT(*) FROM meta_download_log WHERE data_type='dividends'\").fetchone()[0]
print(cnt)
conn.close()
" 2>/dev/null)

            if [ "$DIVS_DONE" -gt 100000 ] 2>/dev/null; then
                echo "  Splits:    ✅ Fertig"
                echo "  Dividends: ✅ Fertig ($DIVS_DONE Ticker)"
                echo ""
                echo "  🎉 ALLE DOWNLOADS ABGESCHLOSSEN!"
                echo "  Staging-Merge + Cleanup stehen noch aus."
                break
            else
                echo "  Splits:    ✅ Fertig"
                echo "  Dividends: 🚀 Starte jetzt..."
                source .venv/bin/activate
                nohup python cli.py download dividends > /tmp/hyperdb_dividends.log 2>&1 &
                echo "  Dividends PID: $!"
            fi
        fi
    fi

    # Disk check
    DISK_FREE=$(df -h /Users/tomschoen/Desktop/ | tail -1 | awk '{print $4}')
    DB_SIZE=$(ls -lh data/hyperdb.duckdb | awk '{print $5}')
    echo ""
    echo "  Disk frei: $DISK_FREE | DB: $DB_SIZE"
    echo "=========================================="

    sleep 1800  # 30 Minuten
done
