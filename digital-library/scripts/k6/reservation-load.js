import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "1m", target: 10 },
    { duration: "3m", target: 40 },
    { duration: "1m", target: 40 },
    { duration: "1m", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<800"],
  },
};

export default function () {
  const base = __ENV.BASE_URL;
  const token = __ENV.TOKEN;
  const headers = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
  const catalog = http.get(`${base}/books`, { headers });
  check(catalog, { "catalog responds": (r) => r.status === 200 });
  const reservation = http.post(
    `${base}/reservations`,
    JSON.stringify({
      book_id: __ENV.BOOK_ID,
      member_id: __ENV.MEMBER_ID,
    }),
    { headers: { ...headers, "Idempotency-Key": `${__VU}-${__ITER}-${Date.now()}` } },
  );
  check(reservation, {
    "reservation accepted": (r) => [200, 201, 202, 409].includes(r.status),
  });
  sleep(0.2);
}
