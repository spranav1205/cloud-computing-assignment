package edu.birla.library.analytics;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.Serializable;
import java.time.Instant;
import java.util.Set;

public class LibraryEvent implements Serializable {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Set<String> SUPPORTED_TYPES = Set.of(
            "ReservationCreated", "ReservationConflict", "LoanCheckedOut", "LoanReturned");

    public String event_type;
    public String book_id;
    public String member_id;
    public String occurred_at;

    public LibraryEvent() {
    }

    public static LibraryEvent parse(String json) {
        try {
            LibraryEvent event = MAPPER.readValue(json, LibraryEvent.class);
            event.validate();
            return event;
        } catch (JsonProcessingException | RuntimeException error) {
            throw new IllegalArgumentException("Invalid library event", error);
        }
    }

    public void validate() {
        if (!SUPPORTED_TYPES.contains(event_type)
                || isBlank(book_id)
                || isBlank(member_id)
                || isBlank(occurred_at)) {
            throw new IllegalArgumentException("Event requires a supported type, book, member, and timestamp");
        }
        try {
            Instant.parse(occurred_at);
        } catch (RuntimeException error) {
            throw new IllegalArgumentException("occurred_at must be an ISO-8601 UTC timestamp", error);
        }
    }

    public long eventTimeMillis() {
        return Instant.parse(occurred_at).toEpochMilli();
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
