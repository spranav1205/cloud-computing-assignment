package edu.birla.library.analytics;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class WindowAggregatorTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void parsesContractAndCountsEventTypesAndDistinctMembers() throws Exception {
        AnalyticsAccumulator accumulator = new AnalyticsAccumulator();
        WindowAggregator.add(accumulator, LibraryEvent.parse(event("ReservationCreated", "member-1")));
        WindowAggregator.add(accumulator, LibraryEvent.parse(event("ReservationConflict", "member-1")));
        WindowAggregator.add(accumulator, LibraryEvent.parse(event("LoanCheckedOut", "member-2")));
        WindowAggregator.add(accumulator, LibraryEvent.parse(event("LoanReturned", "member-2")));

        Map<?, ?> result = mapper.readValue(
                WindowAggregator.toJson("book-1", 60_000L, 120_000L, accumulator),
                Map.class);

        assertEquals("book-1", result.get("book_id"));
        assertEquals("1970-01-01T00:01:00Z", result.get("window_start"));
        assertEquals("1970-01-01T00:02:00Z", result.get("window_end"));
        assertEquals(1, result.get("reservation_count"));
        assertEquals(1, result.get("conflict_count"));
        assertEquals(1, result.get("checkout_count"));
        assertEquals(1, result.get("return_count"));
        assertEquals(2, result.get("unique_members"));
        assertEquals(4, result.get("total_events"));
    }

    @Test
    void rejectsMalformedAndUnsupportedEvents() {
        assertThrows(IllegalArgumentException.class, () -> LibraryEvent.parse("{}"));
        assertThrows(IllegalArgumentException.class, () -> LibraryEvent.parse(
                "{\"event_type\":\"BookAdded\",\"book_id\":\"b1\",\"member_id\":\"m1\","
                        + "\"occurred_at\":\"2026-01-01T00:00:00Z\"}"));
    }

    private static String event(String type, String memberId) {
        return "{\"event_type\":\"" + type
                + "\",\"book_id\":\"book-1\",\"member_id\":\"" + memberId
                + "\",\"occurred_at\":\"2026-01-01T00:00:01Z\"}";
    }
}
