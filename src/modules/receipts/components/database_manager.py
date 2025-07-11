import mysql.connector
from datetime import datetime
from typing import List, Dict, Any, Optional
from decimal import Decimal
from src.database.conexion import conectar
from ..models.receipt_models import ClientData, ProductData, InvoiceSection

class DatabaseManager:
    """Handles database operations for receipts"""
    
    def __init__(self):
        self.conn = conectar()
        self.cursor = self.conn.cursor(dictionary=True)
    
    def get_clients(self) -> List[ClientData]:
        """Get all clients with their type discount information"""
        query = """
            SELECT c.id_cliente, c.nombre_cliente, c.id_grupo, c.id_tipo_cliente, t.descuento 
            FROM cliente c
            LEFT JOIN tipo_cliente t ON c.id_tipo_cliente = t.id_tipo_cliente
        """
        self.cursor.execute(query)
        clients_data = self.cursor.fetchall()
        
        clients = []
        for client_data in clients_data:
            # Validate mandatory fields
            if client_data['id_tipo_cliente'] is None:
                raise ValueError(f"Client {client_data['nombre_cliente']} must have a type assigned")
            if client_data['id_grupo'] is None:
                raise ValueError(f"Client {client_data['nombre_cliente']} must have a group assigned")
            
            clients.append(ClientData(
                id_cliente=client_data['id_cliente'],
                nombre_cliente=client_data['nombre_cliente'],
                id_grupo=client_data['id_grupo'],
                descuento=Decimal(str(client_data['descuento'])) if client_data['descuento'] is not None else Decimal('0'),
                id_tipo_cliente=client_data['id_tipo_cliente']
            ))
        
        return clients
    
    def get_products(self) -> List[ProductData]:
        """Get all products including special ones"""
        query = """
            SELECT p.id_producto, p.nombre_producto, p.unidad_producto, p.es_especial
            FROM producto p
            ORDER BY p.es_especial ASC, p.nombre_producto ASC
        """
        self.cursor.execute(query)
        products_data = self.cursor.fetchall()
        
        products = []
        for product_data in products_data:
            products.append(ProductData(
                id_producto=product_data['id_producto'],
                nombre_producto=product_data['nombre_producto'],
                unidad_producto=product_data['unidad_producto'],
                precio_base=Decimal('0'),  # Will be set dynamically based on client type
                es_especial=bool(product_data['es_especial'])
            ))
        
        return products
    
    def get_product_price(self, product_id: int, client_group_id: int) -> Optional[Decimal]:
        """Get product price for specific client group"""
        query = """
            SELECT precio_base FROM precio_por_grupo 
            WHERE id_producto = %s AND id_grupo = %s
        """
        self.cursor.execute(query, (product_id, client_group_id))
        result = self.cursor.fetchone()
        
        if result:
            return Decimal(str(result['precio_base']))
        return None
    
    def get_client_types(self) -> List[Dict[str, Any]]:
        """Get all client types"""
        query = "SELECT id_tipo_cliente, nombre_tipo FROM tipo_cliente"
        self.cursor.execute(query)
        return self.cursor.fetchall()
    
    def get_groups(self) -> List[Dict[str, Any]]:
        """Get all groups"""
        query = "SELECT id_grupo, clave_grupo FROM grupo ORDER BY clave_grupo"
        self.cursor.execute(query)
        return self.cursor.fetchall()
    
    def get_clients_by_group(self, group_id: int) -> List[ClientData]:
        """Get clients filtered by group with their type information"""
        query = """
            SELECT c.id_cliente, c.nombre_cliente, c.id_grupo, c.id_tipo_cliente, 
                   t.descuento, t.nombre_tipo
            FROM cliente c
            LEFT JOIN tipo_cliente t ON c.id_tipo_cliente = t.id_tipo_cliente
            WHERE c.id_grupo = %s
            ORDER BY c.nombre_cliente
        """
        self.cursor.execute(query, (group_id,))
        clients_data = self.cursor.fetchall()
        
        clients = []
        for client_data in clients_data:
            # Validate mandatory fields
            if client_data['id_tipo_cliente'] is None:
                raise ValueError(f"Client {client_data['nombre_cliente']} must have a type assigned")
            if client_data['id_grupo'] is None:
                raise ValueError(f"Client {client_data['nombre_cliente']} must have a group assigned")
            
            clients.append(ClientData(
                id_cliente=client_data['id_cliente'],
                nombre_cliente=client_data['nombre_cliente'],
                id_grupo=client_data['id_grupo'],
                id_tipo_cliente=client_data['id_tipo_cliente'],
                descuento=Decimal(str(client_data['descuento'])) if client_data['descuento'] is not None else Decimal('0')
            ))
        
        return clients
    
    def get_client_type_name(self, type_id: int) -> str:
        """Get client type name by ID"""
        query = "SELECT nombre_tipo FROM tipo_cliente WHERE id_tipo_cliente = %s"
        self.cursor.execute(query, (type_id,))
        result = self.cursor.fetchone()
        return result['nombre_tipo'] if result else "Desconocido"
    
    def save_invoice(self, client_id: int, products_data: List[Dict[str, Any]], 
                     sections_data: Optional[List[InvoiceSection]] = None) -> Optional[int]:
        """Save invoice to database with optional sections"""
        try:
            # Clear any pending results
            while self.cursor.nextset():
                pass
                
            self.cursor.execute("START TRANSACTION")
            
            # Insert invoice
            self.cursor.execute(
                "INSERT INTO factura (fecha_factura, id_cliente) VALUES (%s, %s)",
                (datetime.now().strftime('%Y-%m-%d'), client_id)
            )
            invoice_id = self.cursor.lastrowid
            
            # Insert invoice metadata
            usa_secciones = bool(sections_data and len(sections_data) > 0)
            self.cursor.execute(
                "INSERT INTO factura_metadata (id_factura, usa_secciones) VALUES (%s, %s)",
                (invoice_id, usa_secciones)
            )
            
            # Handle sections if provided
            section_id_map = {}
            if sections_data:
                for order, section in enumerate(sections_data):
                    self.cursor.execute(
                        "INSERT INTO seccion_factura (id_factura, nombre_seccion, orden_seccion) VALUES (%s, %s, %s)",
                        (invoice_id, section.name, order)
                    )
                    db_section_id = self.cursor.lastrowid
                    section_id_map[section.id] = db_section_id
            
            # Insert invoice details
            for item in products_data:
                if isinstance(item, dict):
                    id_producto = item['producto']['id_producto']
                    cantidad = item['cantidad']
                    precio = item['precio_final']
                    section_id = item.get('section_id')
                else:
                    id_producto = item[0]
                    cantidad = item[1]
                    precio = item[3]
                    section_id = None

                # Map section ID to database section ID
                db_section_id = section_id_map.get(section_id) if section_id else None

                self.cursor.execute(
                    """INSERT INTO detalle_factura 
                    (id_factura, id_producto, cantidad_factura, precio_unitario_venta, id_seccion) 
                     VALUES (%s, %s, %s, %s, %s)""",
                    (invoice_id, id_producto, float(cantidad), float(precio), db_section_id)
                )
            
            self.conn.commit()
            return invoice_id
        
        except mysql.connector.Error as err:
            self.conn.rollback()
            raise Exception(f"Database error: {err}")
        
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Unexpected error: {str(e)}")
        
        finally:
            try:
                while self.cursor.nextset():
                    pass
            except:
                pass
    
    def close(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()