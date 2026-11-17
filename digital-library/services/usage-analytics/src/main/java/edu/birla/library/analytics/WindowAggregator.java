package edu.birla.library.analytics;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.time.Instant;

public final class WindowAggregator {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private WindowAggregator() {
    }

    public static AnalyticsAccumulator add(AnalyticsAccumulator accumulator, LibraryEvent event) {
        switch (event.event_type) {
            case "ReservationCreated" -> accumulator.reservation_count++;
            case "ReservationConflict" -> accumulator.conflict_count++;
            case "LoanCheckedOut" -> accumulator.checkout_count++;
            case "LoanReturned" -> accumulator.return_count++;
            default -> throw new IllegalArgumentException("Unsupported library event type");
        }
        accumulator.unique_members.add(event.member_id);
        return accumulator;
    }

    public static AnalyticsAccumulator merge(
            AnalyticsAccumulator left,
            AnalyticsAccumulator right) {
        left.reservation_count += right.reservation_count;
        left.conflict_count += right.conflict_count;
        left.checkout_count += right.checkout_count;
        left.return_count += right.return_count;
        left.unique_members.addAll(right.unique_members);
        return left;
    }

    public static String toJson(String bookId, long windowStart, long windowEnd, AnalyticsAccumulator accumulator) {
        AnalyticsResult result = new AnalyticsResult();
        result.book_id = bookId;
        result.window_start = Instant.ofEpochMilli(windowStart).toString();
        result.window_end = Instant.ofEpochMilli(windowEnd).toString();
        result.reservation_count = accumulator.reservation_count;
        result.conflict_count = accumulator.conflict_count;
        result.checkout_count = accumulator.checkout_count;
        result.return_count = accumulator.return_count;
        result.unique_members = accumulator.unique_members.size();
        result.total_events = accumulator.reservation_count
                + accumulator.conflict_count
                + accumulator.checkout_count
                + accumulator.return_count;
        try {
            return MAPPER.writeValueAsString(result);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("Could not serialize analytics result", error);
        }
    }
}
