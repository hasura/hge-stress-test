#!/usr/bin/env python

# import asyncio
import humanize
import subprocess
import sys
import psutil
import collections
import time
import datetime
import multiprocessing as mp
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.animation as anim
import numpy as np

# evt_loop = asyncio.get_event_loop()

Event = collections.namedtuple("Event", "ts typ data")


def mk_event(t, data=None):
    e = Event(datetime.datetime.now(), t, data)
    # print(e)
    return e


class StressTest(object):
    def __init__(
        self,
        hge_pid,
        burst_count_min,
        burst_count_incr,
        burst_size_min,
        burst_size_incr,
        burst_interval,
        inter_burst_interval,
        restart_delay,
        loop_count,
        memory_measurement_interval,
    ):
        self.hge_pid = hge_pid
        self.burst_count = burst_count_min
        self.burst_count_min = burst_count_min
        self.burst_count_incr = burst_count_incr
        self.burst_size = burst_size_min
        self.burst_size_min = burst_size_min
        self.burst_size_incr = burst_size_incr
        self.burst_interval = burst_interval
        self.inter_burst_interval = inter_burst_interval
        self.restart_delay = restart_delay
        self.manager = mp.Manager()
        self.q = self.manager.list()
        self.mem_q = self.manager.list()
        self.pending_query_count = mp.Value('i')
        self.loop_count = loop_count
        self.burst_service_time_q = self.manager.list()
        self.query_service_time_q = self.manager.list()
        self.memory_measurement_interval = memory_measurement_interval

    def run_query(self):
        t = time.time()
        self.q.append(mk_event("query_start"))
        with self.pending_query_count.get_lock():
            self.pending_query_count.value += 1
        def run_script():
            subprocess.run(
                "./run_query.sh", stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL
            )
        p = mp.Process(target=run_script)
        p.start()
        p.join()
        with self.pending_query_count.get_lock():
            self.pending_query_count.value -= 1
        t = time.time() - t
        evt = mk_event("query_fin", data=t)
        self.q.append(evt)
        self.query_service_time_q.append(evt)

    def run_burst(self):
        print(f"burst size: {self.burst_size}, burst count: {self.burst_count}")
        t = time.time()
        self.q.append(mk_event("burst_start"))
        procs = []
        for i in range(self.burst_size):
            p = mp.Process(target=self.run_query)
            procs.append(p)
            p.start()
            time.sleep(self.burst_interval)
        self.q.append(mk_event("burst_end"))
        for p in procs:
            p.join()
        t = time.time() - t
        self.q.append(mk_event("burst_fin", data=t))
        self.burst_service_time_q.append(mk_event("burst_fin", data=t))

    def run_loop(self):
        print("running loop")
        self.q.append(mk_event("loop_start"))
        procs = []
        for i in range(self.burst_count):
            p = mp.Process(target=self.run_burst)
            procs.append(p)
            p.start()
            self.burst_size += self.burst_size_incr
            time.sleep(self.inter_burst_interval)
        self.q.append(mk_event("loop_end"))
        for p in procs:
            p.join()
        self.q.append(mk_event("loop_fin"))

    def run_test(self):
        for i in range(self.loop_count):
            print("running loop")
            self.run_loop()
            print("waiting before running loop")
            self.burst_size = self.burst_size_min
            self.burst_count += self.burst_count_incr
            time.sleep(self.restart_delay)

    def run(self):
        hge = psutil.Process(pid=self.hge_pid)
        p = mp.Process(target=self.run_test)
        p.start()

        while True:
            self.mem_q.append(mk_event("mem_rss", data=hge.memory_info().rss))
            time.sleep(self.memory_measurement_interval)

        p.join()

    def visualise(self):
        figure, mem_ax = plt.subplots()
        figure.suptitle(
            f"{self.burst_size}(+{self.burst_size_incr}) reqs + "
          + f"{self.burst_interval}s > "
          + f"{self.burst_count_min}(+{self.burst_count_incr}) bursts + "
          + f"{self.inter_burst_interval}s > "
          + f"{self.loop_count} loops + {self.restart_delay}s")
        # time_ax = mem_ax.twinx()

        mem_ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(humanize.naturalsize))
        # time_ax.set_ylabel("time")

        mem_x_data, mem_y_data = [], []
        query_time_x_data, query_time_y_data = [], []
        burst_time_x_data, burst_time_y_data = [], []

        marker_x_data, marker_labels = [], []

        mem_plt, = mem_ax.plot_date(mem_x_data, mem_y_data, '-', label="mem_rss", color="black")
        self.burst_start = 0
        # burst_time_plt, = mem_ax.plot_date(burst_time_x_data, burst_time_y_data, '-', label="burst time")
        # query_time_plt, = mem_ax.plot_date(query_time_x_data, query_time_y_data, '-', label="query time")

        def update(frame):
            if self.mem_q:
                while self.mem_q:
                    evt = self.mem_q.pop(0)
                    mem_x_data.append(evt.ts)
                    mem_y_data.append(evt.data)
                    mem_plt.set_data(mem_x_data, mem_y_data)

            if self.q:
                while self.q:
                    evt = self.q.pop(0)
                    if evt.typ == "burst_start":
                        self.burst_start = evt.ts
                        # plt.axvline(x=evt.ts, label=f"{evt.typ}", color="#888888")
                    elif evt.typ == "burst_end":
                        # plt.axvline(x=evt.ts, label=f"{evt.typ}", color="#888888")
                        plt.axvspan(self.burst_start, evt.ts, color="#ffc4c8")
                        self.burst_start = None
                    elif evt.typ == "burst_fin":
                        plt.axvline(x=evt.ts, label=f"{evt.typ}", linewidth=3, color="#7bd487")
                    elif evt.typ == "query_start":
                        # plt.axvline(x=evt.ts, label=f"{evt.typ}", color="#eeeeee")
                        pass
                    elif evt.typ == "query_fin":
                        plt.axvline(x=evt.ts, ymin=0.8, ymax=0.9, linewidth=3, label=f"{evt.typ}", color="#cccccc")

            # if not len(self.query_service_time_q) == 0:
            #     evt = self.query_service_time_q.pop(0)
            #     query_time_x_data.append(evt.ts)
            #     query_time_y_data.append(evt.data)
            #     query_time_plt.set_data(query_time_x_data, query_time_y_data)

            # if not len(self.burst_service_time_q) == 0:
            #     evt = self.burst_service_time_q.pop(0)
            #     burst_time_x_data.append(evt.ts)
            #     burst_time_y_data.append(evt.data)
            #     burst_time_plt.set_data(burst_time_x_data, burst_time_y_data)

            figure.gca().relim()
            figure.gca().autoscale_view()
            # return [mem_plt, query_time_plt, burst_time_plt]
            return [mem_plt]

        ani = anim.FuncAnimation(figure, update, interval=500)
        p = mp.Process(target=self.run)
        p.start()
        plt.show()
        p.join()
        

if __name__ == "__main__":
    hge_pid = int(sys.argv[1])
    # stress_test = StressTest(
    #     hge_pid=hge_pid,
    #     burst_count=7,
    #     burst_size=8,
    #     burst_interval=0.5,
    #     inter_burst_interval=20,
    #     restart_delay=30,
    #     loop_count=4,
    #     memory_measurement_interval=0.5,
    # )
    stress_test = StressTest(
        hge_pid=hge_pid,
        burst_count_min=3,
        burst_count_incr=2,
        burst_size_min=20,
        burst_size_incr=10,
        burst_interval=0.1,
        inter_burst_interval=6,
        restart_delay=30,
        loop_count=4,
        memory_measurement_interval=0.5,
    )
    stress_test.visualise()
