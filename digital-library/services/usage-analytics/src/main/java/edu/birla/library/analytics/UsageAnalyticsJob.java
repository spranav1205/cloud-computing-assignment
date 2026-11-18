package edu.birla.library.analytics;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.functions.AggregateFunction;
import org.apache.flink.api.common.serialization.SimpleStringSchema;
import org.apache.flink.connector.base.DeliveryGuarantee;
import org.apache.flink.connector.kafka.sink.KafkaRecordSerializationSchema;
import org.apache.flink.connector.kafka.sink.KafkaSink;
import org.apache.flink.connector.kafka.source.KafkaSource;
import org.apache.flink.connector.kafka.source.KafkaSourceBuilder;
import org.apache.flink.connector.kafka.source.enumerator.initializer.OffsetsInitializer;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.functions.windowing.ProcessWindowFunction;
import org.apache.flink.streaming.api.windowing.assigners.TumblingEventTimeWindows;
import org.apache.flink.streaming.api.windowing.windows.TimeWindow;
import org.apache.flink.util.Collector;

import java.io.IOException;
import java.time.Duration;
import java.util.Map;
import java.util.Properties;

public class UsageAnalyticsJob {
    private static final long CHECKPOINT_INTERVAL_MILLIS = 30_000L;
    private static final long OUT_OF_ORDERNESS_SECONDS = 30L;

    public static void main(String[] args) throws Exception {
        String brokers = requiredEnvironment("KAFKA_BOOTSTRAP_SERVERS");
        String inputTopic = environmentOrDefault("KAFKA_INPUT_TOPIC", "library.events.v1");
        String resultsTopic = environmentOrDefault("KAFKA_RESULTS_TOPIC", "library.analytics.results.v1");
        String groupId = environmentOrDefault("KAFKA_CONSUMER_GROUP", "library-usage-analytics");
        if (inputTopic.equals(resultsTopic)) {
            throw new IllegalArgumentException("Input and results Kafka topics must be different");
        }
        Properties kafkaProperties = kafkaProperties();

        StreamExecutionEnvironment environment = StreamExecutionEnvironment.getExecutionEnvironment();
        environment.enableCheckpointing(CHECKPOINT_INTERVAL_MILLIS);

        KafkaSource<String> source = source(brokers, inputTopic, groupId, kafkaProperties);
        DataStream<LibraryEvent> events = environment
                .fromSource(
                        source,
                        WatermarkStrategy.<String>forBoundedOutOfOrderness(
                                        Duration.ofSeconds(OUT_OF_ORDERNESS_SECONDS))
                                .withIdleness(Duration.ofSeconds(30))
                                .withTimestampAssigner((json, previousTimestamp) ->
                                        LibraryEvent.parse(json).eventTimeMillis()),
                        "library-events")
                .map(LibraryEvent::parse)
                .returns(LibraryEvent.class);

        KafkaSink<String> sink = sink(brokers, resultsTopic, kafkaProperties);
        events
                .keyBy(event -> event.book_id)
                .window(TumblingEventTimeWindows.of(Duration.ofMinutes(1)))
                .aggregate(new EventAggregate(), new WindowResult())
                .sinkTo(sink)
                .name("publish-usage-analytics");

        environment.execute("Digital Library Usage Analytics");
    }

    private static KafkaSource<String> source(
            String brokers,
            String topic,
            String groupId,
            Properties kafkaProperties) {
        KafkaSourceBuilder<String> builder = KafkaSource.<String>builder()
                .setBootstrapServers(brokers)
                .setTopics(topic)
                .setGroupId(groupId)
                .setStartingOffsets(OffsetsInitializer.earliest())
                .setValueOnlyDeserializer(new SimpleStringSchema());
        kafkaProperties.forEach((key, value) -> builder.setProperty(key.toString(), value.toString()));
        return builder.build();
    }

    private static KafkaSink<String> sink(String brokers, String topic, Properties kafkaProperties) {
        return KafkaSink.<String>builder()
                .setBootstrapServers(brokers)
                .setKafkaProducerConfig(kafkaProperties)
                .setRecordSerializer(KafkaRecordSerializationSchema.<String>builder()
                        .setTopic(topic)
                        .setValueSerializationSchema(new SimpleStringSchema())
                        .build())
                .setDeliveryGuarantee(DeliveryGuarantee.AT_LEAST_ONCE)
                .build();
    }

    private static Properties kafkaProperties() throws IOException {
        String json = System.getenv("KAFKA_CLIENT_PROPERTIES");
        Properties properties = new Properties();
        if (json == null || json.isBlank()) {
            return properties;
        }
        Map<String, String> values = new ObjectMapper().readValue(json, new TypeReference<>() {});
        values.forEach((key, value) -> {
            if (key == null || key.isBlank() || value == null || value.isBlank()) {
                throw new IllegalArgumentException("KAFKA_CLIENT_PROPERTIES must contain non-empty string values");
            }
            properties.setProperty(key, value);
        });
        return properties;
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(name + " must be set");
        }
        return value;
    }

    private static String environmentOrDefault(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value;
    }

    private static class EventAggregate
            implements AggregateFunction<LibraryEvent, AnalyticsAccumulator, AnalyticsAccumulator> {
        @Override
        public AnalyticsAccumulator createAccumulator() {
            return new AnalyticsAccumulator();
        }

        @Override
        public AnalyticsAccumulator add(LibraryEvent event, AnalyticsAccumulator accumulator) {
            return WindowAggregator.add(accumulator, event);
        }

        @Override
        public AnalyticsAccumulator getResult(AnalyticsAccumulator accumulator) {
            return accumulator;
        }

        @Override
        public AnalyticsAccumulator merge(AnalyticsAccumulator left, AnalyticsAccumulator right) {
            return WindowAggregator.merge(left, right);
        }
    }

    private static class WindowResult
            extends ProcessWindowFunction<AnalyticsAccumulator, String, String, TimeWindow> {
        @Override
        public void process(
                String bookId,
                Context context,
                Iterable<AnalyticsAccumulator> accumulators,
                Collector<String> output) {
            AnalyticsAccumulator accumulator = accumulators.iterator().next();
            output.collect(WindowAggregator.toJson(
                    bookId,
                    context.window().getStart(),
                    context.window().getEnd(),
                    accumulator));
        }
    }
}
