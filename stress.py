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
import toml
import requests

Event = collections.namedtuple("Event", "ts typ data")
Pair = collections.namedtuple("Pair", "x y")

def mk_event(t, data=None):
    e = Event(datetime.datetime.now(), t, data)
    # print(e)
    return e


class StressTest(object):
    def __init__(
        self,
        hge_pid,
        bursts_per_loop_min,
        bursts_per_loop_incr,
        requests_per_burst_min,
        requests_per_burst_incr,
        request_delay,
        burst_delay,
        loop_delay,
        loop_count,
        measurement_delay,
        wait_for_bursts_to_complete,
        payload_path,
    ):
        self.manager = mp.Manager()
        self.q = self.manager.list()
        self.pending_query_count = mp.Value("i")
        self.mem_q = self.manager.list()
        self.ekg_q = self.manager.list()
        self.burst_service_time_q = self.manager.list()
        self.query_service_time_q = self.manager.list()

        self.hge_pid = hge_pid
        self.bursts_per_loop = bursts_per_loop_min
        self.bursts_per_loop_min = bursts_per_loop_min
        self.bursts_per_loop_incr = bursts_per_loop_incr
        self.requests_per_burst = requests_per_burst_min
        self.requests_per_burst_min = requests_per_burst_min
        self.requests_per_burst_incr = requests_per_burst_incr
        self.request_delay = request_delay
        self.burst_delay = burst_delay
        self.loop_delay = loop_delay
        self.loop_count = loop_count
        self.measurement_delay = measurement_delay
        self.wait_for_bursts_to_complete = wait_for_bursts_to_complete
        self.payload_path = payload_path

        self.burst_start = None
        self.burst_end = None

    def run_query(self):
        t = time.time()
        self.q.append(mk_event("query_start"))
        with self.pending_query_count.get_lock():
            self.pending_query_count.value += 1

        def run_script():
            subprocess.run(
                ["./run_query.sh", self.payload_path],
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
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
        print(
            f"burst size: {self.requests_per_burst}, burst count: {self.bursts_per_loop}"
        )
        t = time.time()
        self.burst_start = datetime.datetime.now()
        self.q.append(mk_event("burst_start"))
        procs = []
        for i in range(self.requests_per_burst):
            p = mp.Process(target=self.run_query)
            procs.append(p)
            p.start()
            time.sleep(self.request_delay)
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
        for i in range(self.bursts_per_loop):
            p = mp.Process(target=self.run_burst)
            procs.append(p)
            p.start()
            self.requests_per_burst += self.requests_per_burst_incr
            time.sleep(self.burst_delay)
            if self.wait_for_bursts_to_complete:
                p.join()
        self.q.append(mk_event("loop_end"))
        if not self.wait_for_bursts_to_complete:
            for p in procs:
                p.join()
        self.q.append(mk_event("loop_fin"))

    def run_test(self):
        for i in range(self.loop_count):
            print("running loop")
            self.run_loop()
            print("waiting before running loop")
            self.requests_per_burst = self.requests_per_burst_min
            self.bursts_per_loop += self.bursts_per_loop_incr
            time.sleep(self.loop_delay)

    def run(self):
        hge = psutil.Process(pid=self.hge_pid)
        p = mp.Process(target=self.run_test)
        p.start()

        while True:
            # TODO account for delay in measurement itself
            self.mem_q.append(mk_event("mem_rss", data=hge.memory_info().rss))
            ekg = requests.get("http://localhost:9080/dev/ekg").json()
            self.ekg_q.append(mk_event("ekg", data=ekg))
            time.sleep(self.measurement_delay)

        p.join()

    def visualise(self):
        figure, mem_ax = plt.subplots()
        figure.suptitle(
            f"{self.requests_per_burst}(+{self.requests_per_burst_incr}) reqs + "
            + f"{self.request_delay}s > "
            + f"{self.bursts_per_loop_min}(+{self.bursts_per_loop_incr}) bursts + "
            + f"{self.burst_delay}s > "
            + f"{self.loop_count} loops + {self.loop_delay}s"
        )
        # time_ax = mem_ax.twinx()

        mem_ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(humanize.naturalsize))
        # time_ax.set_ylabel("time")

        mem_data_x, mem_data_y = [], []
        # query_time_x_data, query_time_y_data = [], []
        # burst_time_x_data, burst_time_y_data = [], []
        ekg_current_bytes_used_x, ekg_current_bytes_used_y = [], []

        marker_x_data, marker_labels = [], []

        (mem_plt,) = mem_ax.plot_date(
            mem_data_x, mem_data_y, "-", label="mem_rss", color="black"
        )
        (ekg_current_bytes_used_plt,) = mem_ax.plot_date(
            ekg_current_bytes_used_x, ekg_current_bytes_used_y, "-", label="ekg_current_bytes_used", color="#0a7787"
        )
        self.burst_start = 0
        # burst_time_plt, = mem_ax.plot_date(burst_time_x_data, burst_time_y_data, '-', label="burst time")
        # query_time_plt, = mem_ax.plot_date(query_time_x_data, query_time_y_data, '-', label="query time")

        def update(frame):
            if self.mem_q:
                while self.mem_q:
                    evt = self.mem_q.pop(0)
                    mem_data_x.append(evt.ts)
                    mem_data_y.append(evt.data)
                    mem_plt.set_data(mem_data_x, mem_data_y)

            if self.ekg_q:
                while self.ekg_q:
                    evt = self.ekg_q.pop(0)
                    ekg_current_bytes_used_x.append(evt.ts)
                    ekg_current_bytes_used_y.append(evt.data['rts']['gc']['current_bytes_used']['val'])
                    ekg_current_bytes_used_plt.set_data(ekg_current_bytes_used_x, ekg_current_bytes_used_y)

            if self.q:
                while self.q:
                    evt = self.q.pop(0)
                    if evt.typ == "burst_start":
                        self.burst_start = evt.ts
                    elif evt.typ == "burst_end":
                        plt.axvspan(
                            self.burst_start, evt.ts, color="#dfdfff", zorder=-2
                        )
                        self.burst_start = None
                    elif evt.typ == "burst_fin":
                        plt.axvline(
                            x=evt.ts, label=f"{evt.typ}", linewidth=2, color="#7bd487"
                        )
                    elif evt.typ == "query_start":
                        # plt.axvline(x=evt.ts, label=f"{evt.typ}", color="#eeeeee")
                        pass
                    elif evt.typ == "query_fin":
                        plt.axvline(
                            x=evt.ts,
                            ymin=0.225,
                            ymax=0.275,
                            linewidth=1,
                            zorder=-1,
                            label=f"{evt.typ}",
                            color="#7bd487",
                        )

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
            return [mem_plt, ekg_current_bytes_used_plt]

        ani = anim.FuncAnimation(figure, update, interval=500)
        p = mp.Process(target=self.run)
        p.start()
        plt.legend(loc="lower left")
        plt.show()
        p.join()


if __name__ == "__main__":
    hge_pid = int(sys.argv[2])
    config = toml.load(sys.argv[1])["stress"]
    print(config)
    # stress_test = StressTest(
    #     hge_pid=hge_pid,
    #     bursts_per_loop=7,
    #     requests_per_burst=8,
    #     request_delay=0.5,
    #     burst_delay=20,
    #     loop_delay=30,
    #     loop_count=4,
    #     measurement_delay=0.5,
    # )
    stress_test = StressTest(
        hge_pid=hge_pid,
        **config,
    )
    stress_test.visualise()
