#!/bin/env bash

# https://stackoverflow.com/questions/7998302/graphing-a-processs-memory-usage

# trap ctrl-c and call ctrl_c()
trap ctrl_c INT

LOG=$(mktemp)
SCRIPT=$(mktemp)
IMAGE=$(mktemp)

echo "Output to LOG=$LOG and SCRIPT=$SCRIPT and IMAGE=$IMAGE"


cat >$SCRIPT <<EOL
set term png small size 800,600
set output "$IMAGE"

set ylabel "RSS"
set y2label "VSZ"

set ytics nomirror
set y2tics nomirror in

set yrange [0:*]
set y2range [0:*]

plot "$LOG" using 3 with lines axes x1y1 title "RSS", "$LOG" using 2 with lines axes x1y2 title "VSZ"
EOL


function ctrl_c() {
	gnuplot $SCRIPT
	xdg-open $IMAGE
	exit 0;
}

while true; do
ps -p $1 -o pid=,vsz=,rss= | tee -a $LOG
sleep 0.2
done
