-- Create separate independent databases for each node
CREATE DATABASE myc_node_1;
CREATE DATABASE myc_node_2;
CREATE DATABASE myc_node_3;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE myc_node_1 TO postgres;
GRANT ALL PRIVILEGES ON DATABASE myc_node_2 TO postgres;
GRANT ALL PRIVILEGES ON DATABASE myc_node_3 TO postgres;

