package edu.birla.library.analytics;

import java.io.Serializable;
import java.util.HashSet;

public class AnalyticsAccumulator implements Serializable {
    public long reservation_count;
    public long conflict_count;
    public long checkout_count;
    public long return_count;
    public HashSet<String> unique_members = new HashSet<>();

    public AnalyticsAccumulator() {
    }
}
