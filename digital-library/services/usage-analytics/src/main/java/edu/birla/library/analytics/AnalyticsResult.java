package edu.birla.library.analytics;

import java.io.Serializable;

public class AnalyticsResult implements Serializable {
    public String book_id;
    public String window_start;
    public String window_end;
    public long reservation_count;
    public long conflict_count;
    public long checkout_count;
    public long return_count;
    public int unique_members;
    public long total_events;

    public AnalyticsResult() {
    }
}
