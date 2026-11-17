FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /workspace
COPY pom.xml .
COPY src ./src
RUN mvn -B -DskipTests package

FROM flink:1.20.1-scala_2.12-java17
COPY --from=build /workspace/target/usage-analytics-1.0.0.jar /opt/flink/usrlib/usage-analytics.jar
