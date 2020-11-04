### Performance benchmarks for liburing/asyncio/uvloop tcp servers

Command used for load test:

```bash
wrk -t12 -c100 -d10s http://localhost:8000
```

1. `asyncio_server.py`

    ```
    Running 10s test @ http://localhost:8000
      12 threads and 100 connections
      Thread Stats   Avg      Stdev     Max   +/- Stdev
        Latency    10.93ms    0.94ms  16.57ms   88.01%
        Req/Sec   597.58     37.88   818.00     65.17%
      71406 requests in 10.03s, 2.72MB read
    Requests/sec:   7120.31
    Transfer/sec:    278.14KB
    ```

2. `uring_server.py`

    ```
    Running 10s test @ http://localhost:8000
      12 threads and 100 connections
      Thread Stats   Avg      Stdev     Max   +/- Stdev
        Latency     6.97ms    2.23ms  45.37ms   98.13%
        Req/Sec     1.15k    82.48     1.70k    92.00%
      137715 requests in 10.03s, 5.25MB read
    Requests/sec:  13724.22
    Transfer/sec:    536.10KB
    ```

3. `asyncio_uring_server.py`

    ```
    Running 10s test @ http://localhost:8000
      12 threads and 100 connections
      Thread Stats   Avg      Stdev     Max   +/- Stdev
        Latency     6.70ms   10.04ms 122.42ms   97.25%
        Req/Sec     1.03k   137.91     1.53k    93.97%
      122176 requests in 10.03s, 4.66MB read
    Requests/sec:  12176.06
    Transfer/sec:    475.63KB
    ```

4. `asyncio_uvloop_server.py`

    ```
    Running 10s test @ http://localhost:8000
      12 threads and 100 connections
      Thread Stats   Avg      Stdev     Max   +/- Stdev
        Latency     4.22ms  688.31us  23.00ms   88.78%
        Req/Sec     1.46k    57.26     2.34k    80.17%
      174261 requests in 10.04s, 6.65MB read
    Requests/sec:  17363.03
    Transfer/sec:    678.24KB
    ```
